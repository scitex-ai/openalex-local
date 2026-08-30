HTTP API Reference
==================

The HTTP relay server provides RESTful access to the OpenAlex database for remote clients.

Starting the Server
-------------------

.. code-block:: bash

   openalex-local relay --port 31292

Interactive API documentation is available at ``http://localhost:31292/docs``

Endpoints
---------

Root
^^^^

.. code-block:: text

   GET /

Returns API information and available endpoints.

Health Check
^^^^^^^^^^^^

.. code-block:: text

   GET /health

Returns server health status.

**Response:**

.. code-block:: json

   {
     "status": "healthy"
   }

Database Info
^^^^^^^^^^^^^

.. code-block:: text

   GET /info

Returns database statistics.

**Response:**

.. code-block:: json

   {
     "total_works": 284000000,
     "fts_indexed": 284000000,
     "mode": "db"
   }

Search Works
^^^^^^^^^^^^

.. code-block:: text

   GET /works?q=<query>&limit=<n>&offset=<n>

Full-text search across titles, abstracts, and authors.

**Parameters:**

- ``q`` (required): Search query (web-search syntax)
- ``limit`` (optional): Maximum results (default: 10)
- ``offset`` (optional): Skip first N results (default: 0)

**Example:**

.. code-block:: bash

   curl "http://localhost:31292/works?q=machine%20learning&limit=5"

**Response:**

.. code-block:: json

   {
     "query": "machine learning",
     "total": 1523847,
     "returned": 5,
     "elapsed_ms": 12.3,
     "works": [
       {
         "openalex_id": "W2741809807",
         "doi": "10.1038/nature12373",
         "title": "...",
         "abstract": "...",
         "authors": ["..."],
         "year": 2013,
         "cited_by_count": 5432
       }
     ]
   }

Get Work by ID
^^^^^^^^^^^^^^

.. code-block:: text

   GET /works/{id_or_doi}

Retrieve a specific work by OpenAlex ID or DOI.

**Examples:**

.. code-block:: bash

   # By OpenAlex ID
   curl "http://localhost:31292/works/W2741809807"

   # By DOI
   curl "http://localhost:31292/works/10.1038/nature12373"

Batch Lookup
^^^^^^^^^^^^

.. code-block:: text

   POST /works/batch

Retrieve multiple works by their IDs or DOIs.

**Request Body:**

.. code-block:: json

   {
     "ids": ["W2741809807", "10.1038/nature12373"]
   }

**Response:**

.. code-block:: text

   {
     "works": [
       {
         "openalex_id": "W2741809807",
         "doi": "10.1038/nature12373",
         "title": "..."
       }
     ],
     "found": 2,
     "not_found": []
   }

Query Syntax
------------

The search endpoint parses queries with PostgreSQL's
``websearch_to_tsquery``, so the syntax is the one web search
engines use:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Syntax
     - Description
   * - ``machine learning``
     - Match both terms (implicit AND)
   * - ``"machine learning"``
     - Match exact phrase
   * - ``machine or deep``
     - Match either term
   * - ``machine -supervised``
     - Exclude term

Python Client
-------------

.. code-block:: python

   from openalex_local import configure_http, search, get

   # Connect to remote server
   configure_http("http://localhost:31292")

   # Use the same API as local mode
   results = search("neural networks", limit=10)
   work = get("10.1038/nature12373")

Environment Variables
---------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Variable
     - Description
   * - ``OPENALEX_LOCAL_API_URL``
     - API URL (default: ``http://localhost:31292``)
   * - ``OPENALEX_LOCAL_MODE``
     - Force ``http`` mode
   * - ``OPENALEX_LOCAL_HOST``
     - Server bind address (default: ``0.0.0.0``)
   * - ``OPENALEX_LOCAL_PORT``
     - Server port (default: ``31292``)
