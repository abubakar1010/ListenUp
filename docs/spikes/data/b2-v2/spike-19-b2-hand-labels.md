# spike-19-b2-hand-labels

Machine: {'cpu': 'Intel(R) Xeon(R) Processor @ 2.10GHz', 'cores': 4, 'memory_gb': 15.7, 'machine': 'x86_64', 'python': '3.12.3', 'omp_num_threads': None, 'date': '2026-10-23'}

- **passages**: all
- **hand-labelled windows**: 0
- **incomplete windows**: accented-es-20090218, clean-f-1221, other-m-1688
- **boundary_matching**: ordered text blocks; no timing cutoff; v2
- **hand_label_gate**: every window labelled (no unlabelled gap over 3 s), all labelled words matched and mean boundary error <= 50 ms

| comparison | words_matched | words_compared | words_unmatched | coverage | mean_ms | median_ms | p90_ms | within_50ms | within_100ms | meets_hand_label_gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| no model output vs hand labels | 0 | 0 | 0 | 0.000 |  |  |  | 0.000 | 0.000 | False |
