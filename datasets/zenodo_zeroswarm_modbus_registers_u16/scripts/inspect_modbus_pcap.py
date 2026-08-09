#!/usr/bin/env python3
"""Inspect classic PCAP for protocol-native Modbus/TCP uint16 fields.

The parser intentionally emits no network identities, timestamps, or checksums.
"""
from __future__ import annotations

import argparse
from array import array
from collections import Counter, defaultdict
import hashlib
import ipaddress
import json
from pathlib import Path
import struct
import sys
from typing import Iterator


MIN_REGISTER_WORDS = 10_000
MIN_ADDRESSED_WORDS = 10_000
MIN_REGISTER_SERIES = 4


def uint16_le_bytes(values: list[int]) -> bytes:
    words = array("H", values)
    if words.itemsize != 2:
        raise ValueError("host unsigned-short width is not 16 bits")
    if sys.byteorder == "big":
        words.byteswap()
    return words.tobytes()


def pcap_packets(path: Path) -> tuple[int, Iterator[tuple[int, bytes]]]:
    handle = path.open("rb")
    header = handle.read(24)
    if len(header) != 24:
        handle.close()
        raise ValueError("truncated PCAP global header")
    magic = header[:4]
    endian_by_magic = {
        b"\xd4\xc3\xb2\xa1": "<",
        b"\xa1\xb2\xc3\xd4": ">",
        b"\x4d\x3c\xb2\xa1": "<",
        b"\xa1\xb2\x3c\x4d": ">",
    }
    if magic not in endian_by_magic:
        handle.close()
        raise ValueError(f"not a supported classic PCAP (magic={magic.hex()})")
    endian = endian_by_magic[magic]
    _, major, minor, _, _, snaplen, linktype = struct.unpack(endian + "IHHIIII", header)
    if (major, minor) != (2, 4) or snaplen <= 0:
        handle.close()
        raise ValueError(f"invalid PCAP version/snaplen: {major}.{minor}/{snaplen}")

    def iterator() -> Iterator[tuple[int, bytes]]:
        packet_index = 0
        try:
            while True:
                record = handle.read(16)
                if not record:
                    break
                if len(record) != 16:
                    raise ValueError(f"truncated packet header at packet {packet_index}")
                _, _, captured, original = struct.unpack(endian + "IIII", record)
                if captured > snaplen or captured > original:
                    raise ValueError(f"invalid packet lengths at packet {packet_index}")
                payload = handle.read(captured)
                if len(payload) != captured:
                    raise ValueError(f"truncated packet payload at packet {packet_index}")
                yield packet_index, payload
                packet_index += 1
        finally:
            handle.close()

    return linktype, iterator()


def tcp_payload(frame: bytes) -> tuple[str, int, str, int, bytes, int, int, int] | None:
    if len(frame) < 14:
        return None
    offset = 14
    ethertype = struct.unpack_from(">H", frame, 12)[0]
    while ethertype in {0x8100, 0x88A8, 0x9100}:
        if len(frame) < offset + 4:
            return None
        ethertype = struct.unpack_from(">H", frame, offset + 2)[0]
        offset += 4
    if ethertype != 0x0800 or len(frame) < offset + 20:
        return None
    version_ihl = frame[offset]
    if version_ihl >> 4 != 4:
        return None
    ihl = (version_ihl & 0x0F) * 4
    if ihl < 20 or len(frame) < offset + ihl:
        return None
    total_length = struct.unpack_from(">H", frame, offset + 2)[0]
    identification = struct.unpack_from(">H", frame, offset + 4)[0]
    flags_fragment = struct.unpack_from(">H", frame, offset + 6)[0]
    if frame[offset + 9] != 6 or (flags_fragment & 0x3FFF):
        return None
    ip_end = min(len(frame), offset + total_length)
    tcp_offset = offset + ihl
    if total_length < ihl + 20 or ip_end < tcp_offset + 20:
        return None
    source_ip = str(ipaddress.ip_address(frame[offset + 12 : offset + 16]))
    destination_ip = str(ipaddress.ip_address(frame[offset + 16 : offset + 20]))
    source_port, destination_port = struct.unpack_from(">HH", frame, tcp_offset)
    receive_window = struct.unpack_from(">H", frame, tcp_offset + 14)[0]
    data_offset = (frame[tcp_offset + 12] >> 4) * 4
    if data_offset < 20 or ip_end < tcp_offset + data_offset:
        return None
    return (
        source_ip, source_port, destination_ip, destination_port,
        frame[tcp_offset + data_offset : ip_end], total_length,
        identification, receive_window,
    )


def complete_adus(payload: bytes) -> Iterator[tuple[int, int, bytes, int]]:
    offset = 0
    while offset + 8 <= len(payload):
        transaction, protocol, length = struct.unpack_from(">HHH", payload, offset)
        if protocol != 0 or not 2 <= length <= 254:
            return
        end = offset + 6 + length
        if end > len(payload):
            return
        unit = payload[offset + 6]
        pdu = payload[offset + 7 : end]
        if not pdu:
            return
        yield transaction, unit, pdu, length
        offset = end


def add_words(
    values: list[int], unit: int, operation: str, start_address: int | None,
    series_counts: Counter[tuple[int, str, int]],
    series_values: dict[tuple[int, str, int], list[int]],
    all_values: set[int],
) -> int:
    for index, value in enumerate(values):
        all_values.add(value)
        if start_address is not None:
            key = (unit, operation, start_address + index)
            series_counts[key] += 1
            series_values[key].append(value)
    return len(values)


def inspect(
    path: Path, *, include_series: bool = False, include_transport: bool = False
) -> (
    dict[str, object]
    | tuple[dict[str, object], dict[tuple[int, str, int], list[int]]]
    | tuple[
        dict[str, object],
        dict[tuple[int, str, int], list[int]],
        dict[str, list[int]],
    ]
):
    linktype, packets = pcap_packets(path)
    if linktype != 1:
        raise ValueError(f"unsupported PCAP linktype {linktype}; expected Ethernet 1")
    packet_count = 0
    modbus_tcp_packets = 0
    complete_adu_count = 0
    function_counts: Counter[str] = Counter()
    series_counts: Counter[tuple[int, str, int]] = Counter()
    series_values: dict[tuple[int, str, int], list[int]] = defaultdict(list)
    pending_reads: dict[tuple[str, int, str, int, int, int, int], tuple[int, int]] = {}
    all_values: set[int] = set()
    total_words = 0
    addressed_words = 0
    correlated_read_responses = 0
    uncorrelated_read_responses = 0
    transport_values: dict[str, list[int]] = defaultdict(list)
    for _, frame in packets:
        packet_count += 1
        tcp = tcp_payload(frame)
        if tcp is None:
            continue
        (
            source_ip, source_port, destination_ip, destination_port, payload,
            total_length, identification, receive_window,
        ) = tcp
        if source_port != 502 and destination_port != 502:
            continue
        modbus_tcp_packets += 1
        if include_transport:
            direction = "response" if source_port == 502 else "request"
            transport_values[f"ipv4_identification_{direction}"].append(identification)
            transport_values[f"ipv4_total_length_{direction}"].append(total_length)
            if direction == "response":
                transport_values["tcp_window_response"].append(receive_window)
        for transaction, unit, pdu, mbap_length in complete_adus(payload):
            complete_adu_count += 1
            if include_transport:
                transport_values[f"modbus_transaction_id_{direction}"].append(transaction)
                transport_values[f"modbus_mbap_length_{direction}"].append(mbap_length)
            function = pdu[0]
            direction = "response" if source_port == 502 else "request"
            function_counts[f"{direction}_fc_{function}"] += 1
            if function & 0x80:
                continue
            if direction == "request" and function in {3, 4} and len(pdu) >= 5:
                start, quantity = struct.unpack_from(">HH", pdu, 1)
                key = (source_ip, source_port, destination_ip, destination_port, transaction, unit, function)
                pending_reads[key] = (start, quantity)
            elif direction == "response" and function in {3, 4} and len(pdu) >= 2:
                byte_count = pdu[1]
                if byte_count % 2 or len(pdu) != byte_count + 2:
                    continue
                values = list(struct.unpack(f">{byte_count // 2}H", pdu[2:]))
                key = (destination_ip, destination_port, source_ip, source_port, transaction, unit, function)
                request = pending_reads.pop(key, None)
                operation = "holding_read" if function == 3 else "input_read"
                start = request[0] if request is not None and request[1] == len(values) else None
                total_words += add_words(values, unit, operation, start, series_counts, series_values, all_values)
                if start is None:
                    uncorrelated_read_responses += 1
                else:
                    correlated_read_responses += 1
                    addressed_words += len(values)
            elif direction == "request" and function == 6 and len(pdu) == 5:
                address, value = struct.unpack_from(">HH", pdu, 1)
                total_words += add_words([value], unit, "single_write", address, series_counts, series_values, all_values)
                addressed_words += 1
            elif direction == "request" and function == 16 and len(pdu) >= 6:
                address, quantity = struct.unpack_from(">HH", pdu, 1)
                byte_count = pdu[5]
                if quantity > 0 and byte_count == quantity * 2 and len(pdu) == byte_count + 6:
                    values = list(struct.unpack(f">{quantity}H", pdu[6:]))
                    total_words += add_words(values, unit, "multiple_write", address, series_counts, series_values, all_values)
                    addressed_words += len(values)
    fingerprints: dict[str, list[str]] = defaultdict(list)
    top_series = []
    for (unit, operation, address), count in series_counts.most_common(50):
        values = series_values[(unit, operation, address)]
        encoded = uint16_le_bytes(values)
        fingerprint = hashlib.sha256(encoded).hexdigest()
        label = f"unit={unit}/{operation}/register={address}"
        fingerprints[fingerprint].append(label)
        top_series.append({
            "unit_id": unit,
            "operation": operation,
            "register_address": address,
            "observations": count,
            "distinct_values": len(set(values)),
            "minimum": min(values),
            "maximum": max(values),
            "transitions": sum(left != right for left, right in zip(values, values[1:])),
            "uint16_le_sha256": fingerprint,
        })
    identical_groups = sorted(
        (labels for labels in fingerprints.values() if len(labels) > 1),
        key=lambda labels: (-len(labels), labels),
    )
    report = {
        "source_file": path.name,
        "source_bytes": path.stat().st_size,
        "pcap_linktype": linktype,
        "packet_count": packet_count,
        "modbus_tcp_packets": modbus_tcp_packets,
        "complete_modbus_adus": complete_adu_count,
        "function_counts": dict(sorted(function_counts.items())),
        "register_words": total_words,
        "addressed_register_words": addressed_words,
        "register_series": len(series_counts),
        "unique_register_sequences": len(fingerprints),
        "identical_sequence_groups": identical_groups,
        "correlated_read_responses": correlated_read_responses,
        "uncorrelated_read_responses": uncorrelated_read_responses,
        "distinct_register_values": len(all_values),
        "minimum": min(all_values) if all_values else None,
        "maximum": max(all_values) if all_values else None,
        "top_register_series": top_series,
    }
    if include_transport:
        report["transport_header_series"] = {
            key: {
                "observations": len(values),
                "distinct_values": len(set(values)),
                "minimum": min(values),
                "maximum": max(values),
                "transitions": sum(left != right for left, right in zip(values, values[1:])),
                "uint16_le_sha256": hashlib.sha256(uint16_le_bytes(values)).hexdigest(),
            }
            for key, values in sorted(transport_values.items())
        }
    if include_series and include_transport:
        return report, dict(series_values), dict(transport_values)
    if include_series:
        return report, dict(series_values)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcap", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.pcap.is_file():
        raise SystemExit(f"missing PCAP: {args.pcap}")
    report, _, _ = inspect(args.pcap, include_series=True, include_transport=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if int(report["register_words"]) < MIN_REGISTER_WORDS:
        raise SystemExit("too few decoded Modbus register words")
    if int(report["addressed_register_words"]) < MIN_ADDRESSED_WORDS:
        raise SystemExit("too few request-correlated/addressed register words")
    if int(report["register_series"]) < MIN_REGISTER_SERIES:
        raise SystemExit("too few distinct unit/operation/register series")
    if int(report["distinct_register_values"]) < 2:
        raise SystemExit("decoded register values are constant")


if __name__ == "__main__":
    main()
