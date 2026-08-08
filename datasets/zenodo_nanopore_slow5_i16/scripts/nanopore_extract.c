#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <slow5/slow5.h>

#define OUTPUT_BUFFER_VALUES 8192
#define INVENTORY_COLUMNS 9

struct sample_stats {
    int16_t minimum;
    int16_t maximum;
    uint64_t zero_count;
    uint64_t transition_count;
};

struct inventory_row {
    uint64_t sequence;
    char *read_id;
    uint64_t value_count;
    uint64_t sample_size_bytes;
    int16_t minimum;
    int16_t maximum;
    uint64_t zero_count;
    uint64_t transition_count;
    char *sample_name;
};

static void die(const char *message) {
    fprintf(stderr, "%s\n", message);
    exit(EXIT_FAILURE);
}

static uint64_t parse_u64(const char *text, const char *field) {
    char *end = NULL;
    errno = 0;
    unsigned long long value = strtoull(text, &end, 10);
    if (errno || end == text || *end != '\0') {
        fprintf(stderr, "invalid %s: %s\n", field, text);
        exit(EXIT_FAILURE);
    }
    return (uint64_t)value;
}

static int16_t parse_i16(const char *text, const char *field) {
    char *end = NULL;
    errno = 0;
    long value = strtol(text, &end, 10);
    if (errno || end == text || *end != '\0' || value < INT16_MIN || value > INT16_MAX) {
        fprintf(stderr, "invalid %s: %s\n", field, text);
        exit(EXIT_FAILURE);
    }
    return (int16_t)value;
}

static void validate_read_id(const char *read_id) {
    if (!read_id || !*read_id) {
        die("empty BLOW5 read ID");
    }
    for (const unsigned char *p = (const unsigned char *)read_id; *p; ++p) {
        if (*p < 0x21 || *p > 0x7e || *p == '\t') {
            die("BLOW5 read ID is not a printable single TSV field");
        }
    }
}

static struct sample_stats measure(const int16_t *values, uint64_t count) {
    if (!values || count == 0) {
        die("encountered an empty raw-signal array");
    }
    struct sample_stats stats = {values[0], values[0], 0, 0};
    int16_t previous = values[0];
    for (uint64_t i = 0; i < count; ++i) {
        int16_t value = values[i];
        if (value < stats.minimum) stats.minimum = value;
        if (value > stats.maximum) stats.maximum = value;
        if (value == 0) ++stats.zero_count;
        if (i && value != previous) ++stats.transition_count;
        previous = value;
    }
    return stats;
}

static void encode_little_endian(const int16_t *values, uint64_t count, uint8_t *output) {
    for (uint64_t i = 0; i < count; ++i) {
        uint16_t word = (uint16_t)values[i];
        output[2 * i] = (uint8_t)(word & 0xffu);
        output[2 * i + 1] = (uint8_t)(word >> 8);
    }
}

static void sample_path(char *path, size_t path_size, const char *directory, uint64_t sequence) {
    int length = snprintf(path, path_size, "%s/%08" PRIu64 ".bin", directory, sequence);
    if (length < 0 || (size_t)length >= path_size) {
        die("sample output path is too long");
    }
}

static void write_sample(const char *path, const int16_t *values, uint64_t count) {
    FILE *output = fopen(path, "wb");
    if (!output) {
        fprintf(stderr, "cannot create %s: %s\n", path, strerror(errno));
        exit(EXIT_FAILURE);
    }
    uint8_t buffer[OUTPUT_BUFFER_VALUES * 2];
    uint64_t offset = 0;
    while (offset < count) {
        uint64_t chunk = count - offset;
        if (chunk > OUTPUT_BUFFER_VALUES) chunk = OUTPUT_BUFFER_VALUES;
        encode_little_endian(values + offset, chunk, buffer);
        if (fwrite(buffer, 2, (size_t)chunk, output) != chunk) {
            fclose(output);
            die("failed to write complete sample");
        }
        offset += chunk;
    }
    if (fclose(output) != 0) {
        die("failed to close complete sample");
    }
}

static void compare_sample(const char *path, const int16_t *values, uint64_t count) {
    FILE *input = fopen(path, "rb");
    if (!input) {
        fprintf(stderr, "cannot open %s: %s\n", path, strerror(errno));
        exit(EXIT_FAILURE);
    }
    uint8_t expected[OUTPUT_BUFFER_VALUES * 2];
    uint8_t actual[OUTPUT_BUFFER_VALUES * 2];
    uint64_t offset = 0;
    while (offset < count) {
        uint64_t chunk = count - offset;
        if (chunk > OUTPUT_BUFFER_VALUES) chunk = OUTPUT_BUFFER_VALUES;
        encode_little_endian(values + offset, chunk, expected);
        if (fread(actual, 2, (size_t)chunk, input) != chunk ||
            memcmp(actual, expected, (size_t)chunk * 2) != 0) {
            fclose(input);
            die("sample differs from decoded BLOW5 raw signal");
        }
        offset += chunk;
    }
    if (fgetc(input) != EOF || ferror(input)) {
        fclose(input);
        die("sample has trailing bytes or a read error");
    }
    if (fclose(input) != 0) {
        die("failed to close verified sample");
    }
}

static int read_inventory_row(FILE *inventory, struct inventory_row *row) {
    char *line = NULL;
    size_t capacity = 0;
    ssize_t length = getline(&line, &capacity, inventory);
    if (length < 0) {
        free(line);
        if (ferror(inventory)) die("failed reading inventory TSV");
        return 0;
    }
    while (length && (line[length - 1] == '\n' || line[length - 1] == '\r')) {
        line[--length] = '\0';
    }
    char *fields[INVENTORY_COLUMNS] = {0};
    char *cursor = line;
    for (int i = 0; i < INVENTORY_COLUMNS; ++i) {
        fields[i] = cursor;
        char *tab = strchr(cursor, '\t');
        if (i + 1 == INVENTORY_COLUMNS) {
            if (tab) die("inventory row has extra columns");
        } else {
            if (!tab) die("inventory row has too few columns");
            *tab = '\0';
            cursor = tab + 1;
        }
    }
    row->sequence = parse_u64(fields[0], "sequence");
    row->read_id = strdup(fields[1]);
    row->value_count = parse_u64(fields[2], "value_count");
    row->sample_size_bytes = parse_u64(fields[3], "sample_size_bytes");
    row->minimum = parse_i16(fields[4], "minimum");
    row->maximum = parse_i16(fields[5], "maximum");
    row->zero_count = parse_u64(fields[6], "zero_count");
    row->transition_count = parse_u64(fields[7], "transition_count");
    row->sample_name = strdup(fields[8]);
    free(line);
    if (!row->read_id || !row->sample_name) die("out of memory reading inventory");
    return 1;
}

static void free_inventory_row(struct inventory_row *row) {
    free(row->read_id);
    free(row->sample_name);
    memset(row, 0, sizeof(*row));
}

static slow5_file_t *open_source(const char *path) {
    slow5_file_t *source = slow5_open(path, "r");
    if (!source) {
        fprintf(stderr, "cannot open BLOW5 source: %s\n", path);
        exit(EXIT_FAILURE);
    }
    return source;
}

static int extract(const char *source_path, const char *output_dir,
                   const char *inventory_path, uint64_t byte_cap) {
    slow5_file_t *source = open_source(source_path);
    FILE *inventory = fopen(inventory_path, "w");
    if (!inventory) die("cannot create raw inventory TSV");
    fprintf(inventory, "sequence\tread_id\tvalue_count\tsample_size_bytes\tminimum\tmaximum\tzero_count\ttransition_count\tsample_name\n");

    slow5_rec_t *record = NULL;
    int result;
    uint64_t sequence = 0;
    uint64_t total_bytes = 0;
    uint64_t omitted_next_bytes = 0;
    while ((result = slow5_get_next(&record, source)) >= 0) {
        validate_read_id(record->read_id);
        if (record->len_raw_signal == 0 || record->len_raw_signal > UINT64_MAX / 2) {
            die("invalid BLOW5 raw-signal length");
        }
        uint64_t sample_bytes = record->len_raw_signal * 2;
        if (sample_bytes > byte_cap - total_bytes) {
            omitted_next_bytes = sample_bytes;
            break;
        }
        ++sequence;
        struct sample_stats stats = measure(record->raw_signal, record->len_raw_signal);
        if (stats.minimum == stats.maximum || stats.transition_count == 0) {
            die("encountered a constant raw-signal read");
        }
        char name[32];
        char path[4096];
        snprintf(name, sizeof(name), "%08" PRIu64 ".bin", sequence);
        sample_path(path, sizeof(path), output_dir, sequence);
        write_sample(path, record->raw_signal, record->len_raw_signal);
        fprintf(inventory,
                "%" PRIu64 "\t%s\t%" PRIu64 "\t%" PRIu64 "\t%d\t%d\t%" PRIu64 "\t%" PRIu64 "\t%s\n",
                sequence, record->read_id, record->len_raw_signal, sample_bytes,
                (int)stats.minimum, (int)stats.maximum, stats.zero_count,
                stats.transition_count, name);
        total_bytes += sample_bytes;
    }
    if (result < 0 && result != SLOW5_ERR_EOF) {
        die("slow5_get_next failed before the bounded prefix was complete");
    }
    if (fclose(inventory) != 0) die("failed to close raw inventory TSV");
    slow5_rec_free(record);
    slow5_close(source);
    if (sequence < 2 || total_bytes < 64ULL * 1024ULL * 1024ULL) {
        die("bounded source prefix is too small for a training family");
    }
    fprintf(stderr,
            "extracted_records=%" PRIu64 " primary_bytes=%" PRIu64
            " byte_cap=%" PRIu64 " omitted_next_record_bytes=%" PRIu64 "\n",
            sequence, total_bytes, byte_cap, omitted_next_bytes);
    return 0;
}

static int verify(const char *source_path, const char *output_dir,
                  const char *inventory_path, uint64_t byte_cap) {
    slow5_file_t *source = open_source(source_path);
    FILE *inventory = fopen(inventory_path, "r");
    if (!inventory) die("cannot open raw inventory TSV");
    char *header = NULL;
    size_t header_capacity = 0;
    if (getline(&header, &header_capacity, inventory) < 0 ||
        strcmp(header, "sequence\tread_id\tvalue_count\tsample_size_bytes\tminimum\tmaximum\tzero_count\ttransition_count\tsample_name\n") != 0) {
        die("raw inventory TSV header mismatch");
    }
    free(header);

    slow5_rec_t *record = NULL;
    struct inventory_row row = {0};
    uint64_t expected_sequence = 0;
    uint64_t total_bytes = 0;
    while (read_inventory_row(inventory, &row)) {
        ++expected_sequence;
        int result = slow5_get_next(&record, source);
        if (result < 0) die("BLOW5 ended before the inventory");
        validate_read_id(record->read_id);
        struct sample_stats stats = measure(record->raw_signal, record->len_raw_signal);
        char expected_name[32];
        snprintf(expected_name, sizeof(expected_name), "%08" PRIu64 ".bin", expected_sequence);
        if (row.sequence != expected_sequence || strcmp(row.read_id, record->read_id) != 0 ||
            row.value_count != record->len_raw_signal || row.value_count > UINT64_MAX / 2 ||
            row.sample_size_bytes != row.value_count * 2 ||
            row.minimum != stats.minimum || row.maximum != stats.maximum ||
            row.zero_count != stats.zero_count || row.transition_count != stats.transition_count ||
            strcmp(row.sample_name, expected_name) != 0) {
            die("inventory metadata differs from decoded BLOW5 record");
        }
        if (row.sample_size_bytes > byte_cap - total_bytes) {
            die("inventory exceeds configured primary-byte cap");
        }
        char path[4096];
        sample_path(path, sizeof(path), output_dir, expected_sequence);
        compare_sample(path, record->raw_signal, record->len_raw_signal);
        total_bytes += row.sample_size_bytes;
        free_inventory_row(&row);
    }
    if (fclose(inventory) != 0) die("failed to close raw inventory TSV");
    if (expected_sequence < 2 || total_bytes < 64ULL * 1024ULL * 1024ULL) {
        die("verified source prefix is too small for a training family");
    }

    int next_result = slow5_get_next(&record, source);
    uint64_t next_bytes = 0;
    if (next_result >= 0) {
        if (record->len_raw_signal > UINT64_MAX / 2) die("invalid next raw-signal length");
        next_bytes = record->len_raw_signal * 2;
        if (next_bytes <= byte_cap - total_bytes) {
            die("inventory omitted a complete source-order record that fits below the cap");
        }
    } else if (next_result != SLOW5_ERR_EOF) {
        die("slow5_get_next failed after the selected prefix");
    }
    slow5_rec_free(record);
    slow5_close(source);
    fprintf(stderr,
            "verified_records=%" PRIu64 " primary_bytes=%" PRIu64
            " byte_cap=%" PRIu64 " next_record_bytes=%" PRIu64 "\n",
            expected_sequence, total_bytes, byte_cap, next_bytes);
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 6 || (strcmp(argv[1], "extract") != 0 && strcmp(argv[1], "verify") != 0)) {
        fprintf(stderr, "usage: %s extract|verify SOURCE.blow5 OUTPUT_DIR INVENTORY.tsv BYTE_CAP\n", argv[0]);
        return EXIT_FAILURE;
    }
    uint64_t byte_cap = parse_u64(argv[5], "byte cap");
    if (byte_cap == 0) die("byte cap must be positive");
    if (strcmp(argv[1], "extract") == 0) {
        return extract(argv[2], argv[3], argv[4], byte_cap);
    }
    return verify(argv[2], argv[3], argv[4], byte_cap);
}
