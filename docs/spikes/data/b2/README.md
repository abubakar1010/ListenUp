# Historical B2 measurements

These JSON files were measured with the original harness. They are retained unchanged
as an audit record, not as validation of the corrected production configuration.

The original alignment tokenizer expanded contractions and handled accents differently
from the production adapter. Boundary comparisons also discarded words displaced by
more than one second. Both code paths have been corrected; aggregate JSON cannot recover
the missing word boundaries or replace a model rerun with the production text targets.

Rebuild the passages and regenerate every B2 setting and comparison using the commands
in [the B2 report](../../19-b2-alignment.md#reproduce). Keep new output separate from
these historical files until the results have been checked. Stage 0 measurements and
independent human labels are still required.
