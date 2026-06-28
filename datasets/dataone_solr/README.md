# DataONE Solr

Paged DataONE Solr repository metadata. The recipe emits homogeneous numeric
table-column samples for object size, replica count, upload/update/modified
timestamps, and year components derived from the same timestamp fields.

Source URL template:
- `https://cn.dataone.org/cn/v2/query/solr/?q=*:*&rows={rows}&start={start}&wt=json&fl=id,size,numberReplicas,dateUploaded,updateDate,dateModified&sort=id%20asc`

Download knobs:
- `DATAONE_SOLR_PAGE_SIZE` defaults to `1000`.
- `DATAONE_SOLR_MAX_PAGES` defaults to `100`.
- `DATAONE_SOLR_MAX_RECORDS` defaults to `100000`.
- `DATAONE_SOLR_MIN_RECORDS` defaults to `5000`.
- `DATAONE_SOLR_REQUEST_DELAY_SECONDS` defaults to `0.1`.

Build knobs:
- `DATAONE_SOLR_MIN_RETAINED_RECORDS` defaults to `5000`.
- `DATAONE_SOLR_MIN_REPLICA_RECORDS` defaults to `1000`.
