# Development Notes

## Adding a Processing Route

Routes are defined in code, not configuration, because each route's meaning
affects safety. Adding one requires all of the following:

1. **Rank it.** Add the route to `ROUTE_RESTRICTIVENESS` in
   `src/document_store/constants.py`. The rank determines its position when
   duplicate content is resolved. Ranks must be unique.

2. **Migrate the schema.** Add a new migration that updates the `CHECK`
   constraints on:
   - `document.processing_route`
   - `document_route_change.from_route` and `to_route`

   SQLite cannot alter a `CHECK` constraint in place, so this requires
   rebuilding the table within the migration.

3. **Map it in config.** Add any `doc_class` that should use the route to
   `[routing]` in `config/config.example.toml`.

4. **Handle it in the pipeline.** Confirm how extraction, chunking, and
   embedding treat the route. Routes that exclude content from chunking must
   be checked wherever chunking occurs.

5. **Update the architecture document.** Record the route in Section 7.3
   and, where relevant, Section 8.1.

6. **Run the consistency tests.** `tests/test_route_consistency.py` fails if
   the constants and the schema disagree.

## Adding a Document Class

(Similar procedure; add to `DOC_CLASSES`, the `document.doc_class` CHECK
constraint, `[routing]`, and `[classification]`.)