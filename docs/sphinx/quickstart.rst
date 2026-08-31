Quickstart
==========

Python API
----------

Basic Search
^^^^^^^^^^^^

.. code-block:: python

   from openalex_local import search, get, count, info

   # Check database status
   db = info()
   print(f"Works: {db['work_count']:,}")

   # Full-text search
   results = search("machine learning", limit=10)
   print(f"Found {results.total:,} matches in {results.elapsed_ms:.1f}ms")

   for work in results:
       print(f"- {work.title} ({work.year})")

Get by ID or DOI
^^^^^^^^^^^^^^^^

.. code-block:: python

   # By OpenAlex ID
   work = get("W2741809807")

   # By DOI
   work = get("10.1038/nature12373")

   if work:
       print(f"Title: {work.title}")
       print(f"Authors: {', '.join(work.authors)}")
       print(f"Abstract: {work.abstract[:200]}...")
       print(f"Concepts: {[c['name'] for c in work.concepts]}")

Work Attributes
^^^^^^^^^^^^^^^

The ``Work`` object has these attributes:

- ``openalex_id`` - OpenAlex ID (e.g., W2741809807)
- ``doi`` - Digital Object Identifier
- ``title`` - Work title
- ``abstract`` - Abstract text
- ``authors`` - List of author names
- ``year`` - Publication year
- ``source`` - Journal/venue name
- ``cited_by_count`` - Number of citations
- ``concepts`` - OpenAlex concepts with scores
- ``topics`` - OpenAlex topics
- ``is_oa`` - Open access status
- ``oa_url`` - Open access URL

Configuration
^^^^^^^^^^^^^

.. code-block:: python

   from openalex_local import configure, configure_http, get_mode

   # Point at a corpus other than this host's
   configure("postgresql://reader@host:55432/scitex")

   # Configure HTTP mode
   configure_http("http://localhost:31292")

   # Check current mode
   print(get_mode())  # "db" or "http"

CLI Usage
---------

.. code-block:: bash

   # Search
   openalex-local search "CRISPR genome editing" -n 5

   # Get by ID
   openalex-local search-by-doi W2741809807
   openalex-local search-by-doi 10.1038/nature12373

   # Show abstracts
   openalex-local search "neural networks" -a

   # JSON output
   openalex-local search "machine learning" --json

   # Status
   openalex-local status

MCP Integration
---------------

For Claude Desktop or other MCP clients:

.. code-block:: json

   {
     "mcpServers": {
       "openalex-local": {
         "command": "openalex-local",
         "args": ["mcp", "start"],
         "env": {
           "SCITEX_STORE_DSN": "postgresql://user@host:55432/scitex"
         }
       }
     }
   }

Available MCP tools:

- ``search`` - Full-text search
- ``search_by_id`` - Get work by ID or DOI
- ``status`` - Database statistics
- ``enrich_ids`` - Batch lookup
