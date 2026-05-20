# corpus/

Mount your COBOL source corpus here. The corpus is **not** part of this repo (license + size).

## Default — CardDemo as sibling

If you cloned `aws-samples/aws-mainframe-modernization-carddemo` as a sibling of this repo:

```bash
ln -s ../CardDemo CardDemo
```

Then `COBOL_CORPUS=$(pwd)/corpus/CardDemo` in your `.env`.

## Alternative — clone directly

```bash
git clone https://github.com/aws-samples/aws-mainframe-modernization-carddemo.git CardDemo
```

## What the pipeline expects

The pipeline assumes the corpus layout from CardDemo:

```
<corpus-root>/
└── app/
    ├── <sub-application>/
    │   ├── cbl/    <- .cbl COBOL source
    │   ├── cpy/    <- .cpy copybooks
    │   ├── dcl/    <- DB2 host variable declarations
    │   ├── ddl/    <- DB2 table definitions
    │   ├── jcl/    <- JCL workflows
    │   ├── bms/    <- BMS map definitions
    │   ├── csd/    <- CICS resource definitions
    │   └── README.md
    └── ...
```

The context-pack phase relies on this sibling-directory convention to pull DCL/DDL/JCL/README for a given `.cbl`.
