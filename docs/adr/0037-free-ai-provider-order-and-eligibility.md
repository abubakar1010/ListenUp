# ADR 0037: Free AI provider order and learner-data eligibility

- Status: Accepted (provider enablement remains gated below)
- Date: 2026-10-11
- Story: [#23, B6](https://github.com/abubakar1010/ListenUp/issues/23)
- Evidence: [B6 comparison and dated official sources](../spikes/b6-ai-providers.md)
- Requirements: NFR-AI-1–10, FR-BL-13, FR-SH-17
- Related: ADR 0009, ADR 0010, ADR 0028

## Context

The MVP requires free tiers or local models and forbids provider training on recordings, transcripts and gists. Issue #23 has no dependencies. Its 825 standard / 375 saving-mode calls per day do not by themselves establish adequate capacity: the selected Groq model permits 1,000 calls but only 200K tokens/day against an estimated 2.1M standard tokens/day. Its 8K TPM also limits bursts. [Groq limits, read 2026-10-11](https://console.groq.com/docs/rate-limits); project demand and calculation are detailed in the spike.

Provider-published benchmarks do not establish gist grading accuracy, all seven Shadow measures, or Stage 0 p95. Spikes #20/#21 still own the self-hosted speech model and performance decision; #18/#19 own transcription/alignment model choices. This decision must not imply that those spikes have passed.

## Decision

Adopt the following ordered directions for #64. Provider names for adapters that do not exist yet are proposals, not registered configuration entries.

| Role / task | Primary | Fallback order | Enablement |
| --- | --- | --- | --- |
| Text AI: key points and gist grading | Groq `openai/gpt-oss-20b` | Local Ollama `qwen3:4b-instruct`; then queue | Verify org limits, ZDR, allowed population/region and golden set. |
| Text AI: round 3 feedback and suggestions | Local Ollama `qwen3:4b-instruct` | Groq 20B only with free headroom reserved for grading; then queue | Benchmark local CPU, memory and golden-set quality. |
| Speech assessment | Self-hosted alignment + wav2vec2 phoneme/GOP + Parselmouth composite, exact checkpoint from #20 | Optional Azure Pronunciation Assessment for supported measures; otherwise queue/unavailable | #20 quality/license decision and #21 latency pass; Azure mapping and consent review before activation. |
| Transcription | Existing `faster-whisper`, CPU int8 `small.en` under ADR 0034 | None initially; queue/unavailable | Retain the merged #18 decision and its Stage 0 validation gates. |
| Alignment | Existing `wav2vec2-ctc`, `WAV2VEC2_ASR_BASE_960H` under ADR 0034 | None initially; queue/unavailable | Retain the merged #19 decision and corrected-harness validation gates. MMS_FA remains subject to its noncommercial restriction if considered as a fallback. |

For local text, choose the 4B non-thinking instruct Q4_K_M artifact as the first benchmark candidate, not as a proven CPU service. Its download is 2.5 GB; total resident memory includes runtime and KV cache. Pin the actual artifact digest/version when implemented. Ollama is the first runtime; llama.cpp remains an implementation alternative for the same weights, not an independent outage fallback. [Ollama model, read 2026-10-11](https://ollama.com/library/qwen3:4b-instruct); [Qwen model card, read 2026-10-11](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507).

**Quota-saving mode starts on at Stage 0.** Rounds 1 and 2 receive deterministic template feedback; reserve hosted quota for key points and gist grades. Preserve System Design §7's cache/coalescing and token/output caps. Its 2.5-call saving estimate conflicts with retaining round 3; #64 must resolve and meter the actual task count rather than treat 375 calls/day as a verified workload. No paid auto-upgrade, account multiplication, or silent charge when a free quota is exhausted.

## Learner-data eligibility

Eligibility is assessed per role, endpoint and configuration, and must be enforced **before** sending data. Unknown training/age/region eligibility means local routing. A no-training policy does not waive consent, retention or region requirements.

| Provider | No-training status and constraints | Selected? |
| --- | --- | --- |
| Local Qwen / local speech engines | Eligible when downloaded weights execute in our environment without cloud routing, prompt logging or training on learner inputs. Audit runtime and checkpoint licenses separately. Qwen Apache-2.0; MMS_FA's noncommercial license prevents unqualified commercial approval if selected as an alignment fallback. Current speech models are owned by ADR 0034. [Qwen, read 2026-10-11](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507); [MMS_FA license, read 2026-10-11](https://docs.pytorch.org/audio/stable/generated/torchaudio.pipelines.MMS_FA.html) | Yes, gated. |
| Groq production inference | No input/output training absent explicit customer permission; require ZDR and no persistence/batch or training feature. US retained-data location; fixed inference region unconfirmed. Cloud access 18+; application use by minors unconfirmed, so minors use local until clarified. [Agreement §2/§4.2, read 2026-10-11](https://console.groq.com/docs/legal/services-agreement); [data controls, read 2026-10-11](https://console.groq.com/docs/your-data) | Yes for text, gated; hosted Whisper not selected. |
| Azure prebuilt PA/STT | Eligible with endpoint logging disabled and no custom training. Microsoft excludes customer data from Speech-model improvement; PA content not retained. Use an approved resource region and required consent; minor end-user contractual interpretation still needs confirmation. [No model improvement, read 2026-10-11](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-encryption-of-data-at-rest); [PA privacy, read 2026-10-11](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/speech-service/speech-to-text/data-privacy-security) | Optional PA fallback after gates, not unconditional full-score fallback. |
| Mistral GA API | Conditional eligibility only with training opt-out verified; Labs/Preview excluded. Free quota/ZDR and exact deployment conditions unconfirmed. [Terms, read 2026-10-09](https://legal.mistral.ai/terms/commercial-terms-of-service/) | No initial routing. |
| Cerebras | No-training eligible in principle; only finite trial, production/geography constraints remain. [Terms, read 2026-10-09](https://cloud.cerebras.ai/terms); [trial limits, read 2026-10-11](https://inference-docs.cerebras.ai/support/rate-limits) | No. |
| Speechace | Explicit no training on audio/transcripts/scores; retention defaults to 90 days, ZDR needs Enterprise. Respect restrictions on evaluation/training of competing models. [Privacy, read 2026-10-11](https://www.speechace.com/api-privacy-policy/); [terms, read 2026-10-11](https://www.speechace.com/api-terms-of-service/) | No recurring free plan; not selected. |
| Deepgram STT | Conditional eligibility only with `mip_opt_out=true` verified for every request and approved regional endpoint; default requests participate in model improvement. [Data controls, read 2026-10-11](https://developers.deepgram.com/trust-security/your-data) | No; one-off credit, keep transcription local. |
| Gemini unpaid, OpenRouter Free, SpeechSuper | Not approved: ordinary unpaid Gemini trains; Free OpenRouter cannot establish fixed eligible upstream routing; SpeechSuper explicit no-training coverage unconfirmed. [Gemini terms, read 2026-10-09](https://ai.google.dev/gemini-api/terms); [OpenRouter plan, read 2026-10-11](https://openrouter.ai/pricing); [SpeechSuper privacy, read 2026-10-11](https://www.speechsuper.com/privacy.html) | No. |

GitHub Models is retired and is not a candidate. [Official retirement notice, read 2026-10-11](https://docs.github.com/en/github-models).

## Consequences and handoff

Hosted-free-only text operation cannot cover expected tokens. Local overflow is necessary; if local quality or CPU capacity fails, queue rather than silently grade with an unaccepted model. Azure's five-hour monthly free pool supports only about 66–100 three-round sessions/month at 60–90 seconds/round and cannot replace primary local scoring. It covers selected pronunciation/fluency measures, not necessarily all seven; partial output cannot be reported as a complete assessment. [Pricing, read 2026-10-09](https://azure.microsoft.com/en-us/pricing/details/speech/); calculation in spike.

#64 must implement per-task routes, eligibility controls (`trains_on_inputs: false` only for verified configurations), quota admission across requests/tokens/audio, schema/range validation, provenance and golden-set acceptance. An eligible provider may still be unavailable or unsuitable. Capture content-free counters for input/output/reasoning/cache tokens, audio seconds, fallback frequency, queue delay and projected cost. Exact org/account limits and the no-training/ZDR settings are launch evidence, not guessed defaults.

The proposed role-level text order is Groq → Ollama with task overrides above. Speech order is the #20 local composite → optionally Azure for supported measures. Existing transcription/alignment order is retained. #64 assigns actual adapter IDs/options; this research PR does not edit `ai.yaml` or implement adapters.

## Revisit triggers

- Immediately on a terms/training/retention/age/region change, lost opt-out/ZDR, model retirement, or unconfirmed eligibility for a newly supported population: disable hosted routing until revalidated.
- Before enabling an adapter or changing model/version/prompt/schema: pass the NFR-AI-6 shared set (~50 gists/~50 recordings), validate task-specific outputs, and record latency on the Stage 0 host. No accuracy pass is claimed by this research.
- When #18/#19/#20/#21 publishes its model, license, quality or latency decision; specifically clear MMS_FA's noncommercial restriction and assess all seven measures before commercial deployment.
- When 75% of any free allowance is consumed, or 429/queue/latency telemetry threatens the task budget: invoke saving/fallback immediately under #64, then review capacity. More requests do not solve a token or concurrency bottleneck.
- Before a paid plan is enabled: review actual input/output mix, projected monthly spend, terms and region, approve a budget and hard limits, and keep a free/local fallback. Groq's documented 20B rates permit a low-cost planned upgrade, not automatic expenditure. [Rates, read 2026-10-11](https://console.groq.com/docs/models).
- Re-read provider sources at launch and at least monthly while hosted learner-data processing is enabled; recheck prices at purchase. Expand local weights or add hardware only after measured quality/capacity evidence.
