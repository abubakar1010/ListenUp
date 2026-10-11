# B6: Free AI providers, quotas and learner-data eligibility

Research for [issue #23](https://github.com/abubakar1010/ListenUp/issues/23), read 2026-10-11. Its Dependencies section says **None**. It asks which no-training hosted text tier can cover 825 standard or 375 saving-mode calls/day, whether hosted transcription/pronunciation is worth adding, whether saving mode starts on, and what local LLM size to use. Provider wiring belongs to #64.

## Scope and evidence

Read [SRS §8.7](../design/srs.md#87-ai-provider-strategy-free-first-no-lock-in), [System Design §7](../design/system-design.md#7-ai-quota-and-cost-efficiency), and ADRs [0009](../adr/0009-ai-behind-ports-and-a-configuration-driven-gateway.md), [0010](../adr/0010-self-hosted-speech-pipeline-for-recordings.md) and [0028](../adr/0028-ai-ports-gateway-and-self-hosted-speech-adapters.md). Other design sections were not used. Requirements: NFR-AI-1–10, especially no training (7), free-first (3), validated schemas (4), golden-set acceptance (6), quota/fallback handling (8) and planned paid costs (10).

Every provider fact below links to an official documentation, terms, model-card or maintainer page; the citation label contains the actual date read. Dates are access dates, not promises that the fact will remain current. **Unconfirmed** means the public source did not establish the fact; it does not mean zero usage, zero retention, or permission. Prices are USD before taxes. Monthly equivalents of daily allowances use **30 days** and are calculations, not monthly entitlements. No account was created, no paid plan enabled, no learner data sent, and no quality or latency benchmark run.

Eligibility below means the no-training requirement can be met, subject to the listed configuration and legal constraints. It is distinct from selection and from passing the golden set. Never infer no training solely from no retention.

## Text AI: free limits and task suitability

RPM/RPD = requests/minute/day; TPM/TPD = tokens/minute/day. Account-specific limits must be checked before #64 enables a provider.

| Candidate | Free daily/monthly quota and rate | Structured output, quality signals and expected latency | Paid path | Assessment |
| --- | --- | --- | --- | --- |
| **Groq, `openai/gpt-oss-20b`** | 1,000 RPD; 200,000 TPD; 30 RPM; 8,000 TPM, organization-wide. No separate monthly allowance published; calculated 30-day ceilings 30,000 calls/6M tokens, with daily caps still binding. Exact org limits may differ. [G1 · 2026-10-11] | OpenAI-compatible API; strict JSON-schema output supported. Production model, advertised 1,000 tokens/s; this is generation throughput, not end-to-end p95. Gist/key-point accuracy and time to first token **unconfirmed**. [G2 · 2026-10-11] [G5 · 2026-10-09] [G6 · 2026-10-09] | $0.075/M input and $0.30/M output; Developer base 1,000 RPM/250K TPM. [G2 · 2026-10-11] | Selected hosted primary; token quota requires local overflow. |
| **Mistral API, GA small models** | Free mode exists, but exact daily/monthly requests/tokens and rate limits are account Limits-page values: **unconfirmed publicly**. Do not budget an assumed allowance. [M1 · 2026-10-09] | JSON schema support; Small 4/Ministral are small-model candidates. Task accuracy, CPU comparison and hosted p95 **unconfirmed**. [M4 · 2026-10-09] [M5 · 2026-10-09] | Small 4 $0.15/M input, $0.60/M output; Ministral 3 3B $0.10/$0.10. Regional inference +10%. [M5 · 2026-10-09] | Conditional alternative after account quota and training settings are recorded; excluded from initial order. |
| **Google Gemini API, unpaid** | Free tokens on eligible models; actual active project RPM/TPM/RPD shown in AI Studio, vary by tier/model. Daily/monthly usable quota **unconfirmed publicly**. [GE1 · 2026-10-09] [GE2 · 2026-10-09] | JSON-schema generation supported; ListenUp quality and end-to-end latency **unconfirmed**. [GE4 · 2026-10-09] | Paid pricing depends on model; documented Gemini 3.8 Flash introductory input/output $0.75/$3.75 per M through 2026-12-31, then increases. Recheck on purchase. [GE1 · 2026-10-09] | Unpaid training policy fails NFR-AI-7; age restrictions also matter. |
| **Cerebras, `gpt-oss-120b`** | **Trial only:** $5 after verified payment method, expires after 30 days; no recurring free tier. Trial 5 RPM, 30K uncached TPM/90K total TPM, 1M TPH/TPD; RPD/monthly token cap not published. [C1 · 2026-10-11] | Strict schema output; advertised ~3,000 tokens/s for GPT-OSS 120B; task quality and p95 **unconfirmed**. [C2 · 2026-10-11] [C5 · 2026-10-09] | $0.35/M input, $0.75/M output. Developer plan described as evaluation/exploration, not production; production plan needs agreement. [C2 · 2026-10-11] | Not a sustainable free fallback. |
| **OpenRouter Free** | 50 requests/day (calculated 1,500/30 days), 20 RPM; free model token quotas vary, **unconfirmed**. No monthly pool established. [O1 · 2026-10-11] [O4 · 2026-10-09] | Schema support varies by model. Free plan lacks policy/provider/region routing controls; no stable model-quality or latency baseline established. [O1 · 2026-10-11] [O3 · 2026-10-09] | Standard charges upstream model price plus 5.5% credit-purchase fee; exact cost requires a pinned provider/model. [O1 · 2026-10-11] | Initial Free routing cannot guarantee our no-training policy; too few calls anyway. |
| **GitHub Models** | Retired 2026-07-30; playground, inference and BYOK unavailable. Current quota/rate/paid cost: N/A. [GH1 · 2026-10-11] | N/A after retirement. [GH1 · 2026-10-11] | N/A. [GH1 · 2026-10-11] | Removed from consideration. Historical free limits are irrelevant. |
| **Self-hosted Ollama / llama.cpp, Qwen3 4B Instruct** | No vendor request/token/day/month allowance when running local weights; throughput is bounded by our hardware and queue (deployment inference). Local model artifact `qwen3:4b-instruct`, Q4_K_M, 4.02B parameters, 2.5 GB. [L1 · 2026-10-11] | Ollama schema constraints and OpenAI compatibility; llama.cpp also has a compatible server/schema constraints. Qwen publishes instruction-following evaluations, not a ListenUp grading result. CPU p50/p95 and concurrent capacity **unconfirmed**; benchmark before enabling overflow. [L2 · 2026-10-11] [L3 · 2026-10-09] [L5 · 2026-10-11] [L6 · 2026-10-09] | $0 API fee for local execution; compute, RAM and electricity are our cost (deployment inference). [L4 · 2026-10-09] [L7 · 2026-10-09] | Selected fallback, and primary for routine feedback. Artifact size is not peak RAM. |

### Text data policies and other terms

| Candidate | Training / switch-off / learner-data eligibility | Retention and region | Commercial use and age |
| --- | --- | --- | --- |
| **Groq** | Agreement §4.2 excludes input/output training unless customer explicitly permits it. Eligible for approved populations with no permission granted; require ZDR as an additional project policy. [G4 · 2026-10-11] | Reliability/abuse retention can be up to 30 days; all customers may enable ZDR, disabling persistence features. Content-free usage metadata remains. Retained data is in US GCP buckets; inference-region guarantee **unconfirmed**. [G3 · 2026-10-11] | Customer-app integration allowed. Cloud access is 18+; whether this permits under-18 application end users is **unconfirmed**. Route minors to local execution pending clarification. [G4 · 2026-10-11] |
| **Mistral GA API** | Commercial terms allow training under product defaults/opt-in unless opted out; opt-out is available. Labs/Preview exception can train regardless of ordinary opt-out/ZDR. Eligible only after evidence of opt-out, GA endpoint and no feedback submission; Labs excluded. [M2 · 2026-10-09] | Privacy policy: rolling 30-day abuse retention unless ZDR. Supported regional EU/US inference available; residency and ZDR for the exact free account **unconfirmed**. [M3 · 2026-10-09] [M5 · 2026-10-09] | Commercial integration permitted. No personal data of under-13/below-consent-age children; minors need parental consent. [M2 · 2026-10-09] |
| **Gemini unpaid / paid** | Ordinary unpaid content may improve products/models and be human-reviewed: **ineligible**. Active-billing paid service does not use prompts/responses for product improvement. Regional unpaid exceptions do not establish eligibility for our deployment. [GE3 · 2026-10-09] | Paid abuse/legal logging duration **unconfirmed**; processing may occur in countries where Google/agents operate. Unpaid retention duration **unconfirmed**. [GE3 · 2026-10-09] | Intended for professional/business use; operator 18+, and clients may not target or likely be accessed by under-18s. Paid status does not remove this restriction. [GE3 · 2026-10-09] |
| **Cerebras** | Terms exclude training/fine-tuning on service content; privacy says inference inputs/outputs not retained. No-training eligible in principle, but not selected. [C3 · 2026-10-09] [C4 · 2026-10-09] | No input/output retention stated; inference geography **unconfirmed**. [C4 · 2026-10-09] | Business/API integration permitted; account minimum 13 or local digital-consent age. Exact minor end-user application interpretation **unconfirmed**. [C3 · 2026-10-09] |
| **OpenRouter** | Upstream terms and training vary; selecting approved upstreams/opt-out is necessary. Free plan lacks policy routing, so **not approved for learner data**. [O1 · 2026-10-11] [O2 · 2026-10-11] | Upstream retention varies; fixed retention/region for Free **unconfirmed**. [O2 · 2026-10-11] | Commercial application use subject to upstream terms; end-user age eligibility **unconfirmed** in this research. [O2 · 2026-10-11] |
| **GitHub Models** | Service retired; eligibility/retention/region/commercial/age review not pursued for an unavailable service. [GH1 · 2026-10-11] | N/A. | N/A. |
| **Local Qwen + runtime** | Eligible: infer with downloaded weights in our environment, without cloud inference or training on learner inputs (deployment decision). Qwen Apache-2.0, runtimes MIT. [L1 · 2026-10-11] [L4 · 2026-10-09] [L7 · 2026-10-09] | Our storage/region/retention controls apply; prevent prompt logging and outbound cloud routing (deployment decision). | Licenses permit commercial use with notices; no age minimum in these software licenses. Product consent obligations remain ours. [L4 · 2026-10-09] [L5 · 2026-10-11] [L7 · 2026-10-09] |

Other local model candidates: Phi-4-mini-instruct is 3.8B/MIT [L8 · 2026-10-09]; Gemma 3 4B has custom Gemma terms [L9 · 2026-10-09]. Neither has confirmed ListenUp accuracy/CPU latency. Prefer Qwen's small non-thinking instruct artifact and permissive license; this is a selection hypothesis, not a measured quality ranking. If 4B fails the golden set, evaluate a larger local model before changing the deployment budget; do not assume larger weights meet CPU latency.

### Capacity and paid planning

Using issue #23 and System Design §7, standard demand is **825 calls/day**, or **24,750/30 days**. The approximate 14K tokens/session and 150 sessions/day imply **2.1M tokens/day**, or **63M/30 days** (calculation; no cache credit assumed). Groq's 1,000 RPD covers the request count, but **200K/2.1M = 9.5%** of the token estimate, about **14 whole standard sessions/day**. Its 8K TPM permits roughly two 4K-token tasks per minute, so bursts need scheduling even before the daily allowance is spent. [G1 · 2026-10-11]

Saving-mode planning remains **375 calls/day / 11,250 per 30 days**, as requested by #23. System Design §7.2 says 5.5→2.5 calls, but retaining round 3 would arithmetically yield 3.5, and §7.1's weighted tokens yield 12.5K rather than its rounded 14K. These are **design-estimate inconsistencies**, not provider facts. This spike does not amend the design: #64 must count actual task/token usage and resolve the retained-call definition. Removing two 1.5K feedback calls suggests roughly 9.5K–11K tokens/session, **1.425M–1.65M/day**, still far above 200K (calculation/inference). Saving mode alone cannot make hosted-only free operation sustainable.

**Recommendation:** start saving mode **on** for Stage 0; keep caching/coalescing, task token caps and local overflow. Key points/gist: Groq first, local Qwen second. Round feedback/suggestions: local Qwen first, Groq second only when free headroom exists; rounds 1–2 use templates while saving mode is on. Reserve hosted quota for grading. When every accepted candidate is unavailable, queue and show delayed/unavailable feedback; never return a fabricated grade or silently spend money (NFR-AI-4/6/8).

For the optional paid move, Groq 20B costs `input_M × $0.075 + output_M × $0.30`. At the design's 63M monthly total, a hypothetical 90% input/10% output split is **$6.14/month**; all-output is **$18.90/month** (calculations, not a budget guarantee; reasoning tokens/output caps, retries and actual usage must be measured). [G2 · 2026-10-11] Record input/output/cache/reasoning usage separately, daily quota utilization, fallback/queue frequency and projected monthly dollars in the NFR-AI-10 admin view. Paid activation requires a deliberate budget decision and renewed terms/golden-set review, not automatic upgrading on 429.

## Speech assessment

Speech scoring and text feedback are separate roles. JSON score responses are structured, but adapters must map their fields to our validated port; vendor scoring rubrics do not establish all seven Shadow measures or comparison against the original clip.

| Candidate | Free daily/monthly quota and rate | Training, retention, region, commercial and age terms | Quality / latency / paid cost | Decision |
| --- | --- | --- | --- | --- |
| **Self-hosted composite: alignment + wav2vec2 phoneme/GOP + Parselmouth** | No external quota/API charge; local CPU/queue bound (deployment inference). Exact model, license combination, peak RAM and throughput remain #20/#21 outputs, **unconfirmed** today. [P1 · 2026-10-11] [P2 · 2026-10-11] | Learner data stays in our environment; no provider training permitted (deployment decision/ADR 0010). Each eventual checkpoint and dependency license needs approval in #20; a research recipe is not itself a licensed deployable provider. | #20 tests clear vs poor recordings; #21 tests p95 <50s for a 75s recording on two threads. Both are open; no pass claimed. [P1 · 2026-10-11] [P2 · 2026-10-11] | **Selected primary approach**, gated by #20/#21; exact checkpoint pending their decision. |
| **GOPT, research comparator** | Local, no vendor quota; CPU latency **unconfirmed**. [S1 · 2026-10-11] | Maintainer BSD-3-Clause code; complete pretrained/ASR artifact license chain **unconfirmed**. Local execution can avoid data transfer. [S1 · 2026-10-11] | Published SpeechOcean762 sentence PCC 0.742, phone 0.612, word 0.549; not validation of our seven measures. Maintainer flags an inference tutorial bug. [S1 · 2026-10-11] | Useful #20 comparator; not production fallback. |
| **Azure Pronunciation Assessment (PA)** | F0 real-time pool **5 audio hours/month**; no independent daily allowance published; **1 concurrent** request. PA baseline billed as STT; prosody add-on eligibility within F0 **unconfirmed**. [A1 · 2026-10-09] [A2 · 2026-10-09] [A3 · 2026-10-09] | Microsoft says customer data does not improve Speech models; PA data not retained/stored. Disable endpoint logging, avoid custom training. Resource region controls processing; commercial customer solutions allowed. Speech-specific end-user age floor **unconfirmed**; consent/biometric notices are customer obligations. [A4 · 2026-10-11] [A5 · 2026-10-11] [A6 · 2026-10-11] [A7 · 2026-10-11] | Accuracy/fluency/completeness and phoneme scores; prosody en-US. >30s audio requires continuous mode; miscue handling needs app-side comparison. No numeric ListenUp p95 confirmed. PA baseline S0 $1/hour and prosody $0.30/hour example region price; recheck selected region/contract. [A1 · 2026-10-09] [A3 · 2026-10-09] | No-training **eligible**, optional limited fallback for supported measures only after golden set and adapter mapping. Do not represent PA as all seven measures. |
| **Speechace API** | **14-day trial**, not recurring free allowance. Trial request quota and concurrency/RPM **unconfirmed**. [SA1 · 2026-10-11] [SA4 · 2026-10-11] | Explicitly no training on audio, transcripts or scores. Default **90-day** retention plus up to 48h deletion delay; shorter/ZDR needs Enterprise agreement. Region selected at API key; account admins 18+, end users any age with required consent. Commercial API use allowed; competitor/model evaluation restrictions must be honored. [SA2 · 2026-10-11] [SA3 · 2026-10-11] | Pronunciation/fluency fields; provider reports 0.9 correlation in hold-outs, not our golden set. Pro max 45s conflicts with 60–90s segments; Premium max 2min, $125/month includes 10K 15s units, $0.0125/unit listed. p95 **unconfirmed**. [SA1 · 2026-10-11] | No-training eligible in principle; not selected: finite trial, long retention, segment/plan constraints. |
| **SpeechSuper API** | Free trial advertised; exact requests/day/month, expiry and concurrency **unconfirmed**. [SS1 · 2026-10-11] [SS4 · 2026-10-11] | Policy says audio only used for analysis/feedback and promptly permanently discarded. Explicit no-training coverage of transcripts/derived scores and opt-out **unconfirmed**; processing region **unconfirmed** (company location is not residency). Accounts >18; end-user rule **unconfirmed**. Commercial API offered; terms prohibit using results to train/test/evaluate another scoring model. [SS2 · 2026-10-11] [SS3 · 2026-10-11] | Word/phoneme/sentence scoring advertised; task accuracy and p95 **unconfirmed**. PAYG monthly minimum $20; paragraph $0.008/request, unscripted Basic $0.030, Pro $0.035. [SS1 · 2026-10-11] | **Not approved for learner data** without explicit no-training terms; no automatic fallback. |

Azure's 300 free minutes/month cover only **66–100 three-round sessions/month** at 60–90s/round (calculation), versus Stage 0's 150 sessions/day implied by #23. A full 30-day month of those rounds would be 225–337.5 hours; S0 baseline would be about **$225–337.50**, with prosody about **$292.50–438.75**, before any applicable credits/tax (calculation using [A1 · 2026-10-09]). Keep self-hosted primary. If it fails quality/latency, revisit segment/model/GPU/budget with #20/#21 evidence. Azure can assess supported measures within its small free pool; exhaustion or missing required measures must queue or return unavailable, not hide the omission. Speechace/SpeechSuper cannot be used to produce labels for evaluating/training our competing speech scorer where their terms forbid that. [SA3 · 2026-10-11] [SS3 · 2026-10-11]

## Transcription and alignment: retain ADR 0028

These roles remain self-hosted. The hosted screen answers #23's “worth adding?” question; it does not change #18/#19 or the transcription session's configuration.

| Candidate | Quota/rate and data terms | Quality/latency and paid move | Recommendation |
| --- | --- | --- | --- |
| **faster-whisper transcription; wav2vec2-CTC `MMS_FA` alignment** | ADR 0028 selects local CPU int8 `base.en` and torchaudio MMS_FA provisionally until #18/#19. No provider quota; local deployment controls retention/region/training. faster-whisper MIT; Whisper weights MIT. MMS_FA checkpoint is **CC-BY-NC-4.0**, so commercial deployment is **not cleared** merely because torchaudio code is open-source. [T1 · 2026-10-11] [T2 · 2026-10-11] [T3 · 2026-10-11] | faster-whisper maintainer benchmarks signal efficiency, not Stage 0 p95; exact quality/latency stays with #18/#19. [T1 · 2026-10-11] | Keep provider order unchanged. Escalate MMS_FA's noncommercial checkpoint license to #19 before commercial launch; choose commercially licensed weights there if needed. |
| **Groq Whisper large-v3 / turbo** | 20 RPM, 2K RPD; 7,200 audio seconds/hour and 28,800/day = 2h/hour, **8h/day**; calculated 240h/30 days, daily/hourly caps bind. Same Groq no-training/ZDR/US-retention and age conditions as above. [G1 · 2026-10-11] [G3 · 2026-10-11] [G4 · 2026-10-11] | Speech transcription, not speech assessment. Paid large-v3 $0.111/hour, turbo $0.04/hour; task WER and latency **unconfirmed**. [G2 · 2026-10-11] | Eligible under listed conditions, but defer adding another speech dependency unless #18 finds local transcription insufficient. |
| **Azure real-time STT** | Same 5h/month F0 pool and 1 concurrent request; no retention/no Speech-model improvement, resource region. [A1 · 2026-10-09] [A2 · 2026-10-09] [A4 · 2026-10-11] [A5 · 2026-10-11] [A6 · 2026-10-11] | Streaming API; no measured local comparison. S0 example $1/hour. [A1 · 2026-10-09] | Not worth initial wiring for a shared, small free pool. |
| **Deepgram Nova-3** | One-off **$200 credit**, no expiry, no recurring daily/monthly allowance. Docs say prerecorded concurrency starts at 200; pricing page says REST up to 50: **conflict, exact trial account limit unconfirmed**. Default MIP retains/trains; every request must set `mip_opt_out=true`, giving no training and content ZDR; regional endpoint plus opt-out keeps content within region. [D1 · 2026-10-11] [D2 · 2026-10-11] [D3 · 2026-10-11] | Nova-3 is recommended by provider, not verified on our corpus; end-to-end p95 **unconfirmed**. Prerecorded monolingual $0.0043/min; opt-out no longer increases published rates. Commercial API access allowed; operator eligibility 18+ or higher consent age, minor application end-user interpretation **unconfirmed**. [D1 · 2026-10-11] [D4 · 2026-10-11] [D5 · 2026-10-11] | Conditional no-training eligible with mandatory verified opt-out; useful future benchmark, not a renewable free fallback. |

No hosted alignment provider is selected. Alignment quality, model licensing and fallback belong to #19; retries cannot repair an unalignable word. A missing alignment must be represented honestly, as ADR 0028 requires.

## Recommended order and enablement gates

| Role/task | Primary → fallback | Why and learner-data gate |
| --- | --- | --- |
| Text: key points, gist grade | Groq `openai/gpt-oss-20b` → local Ollama `qwen3:4b-instruct` → queue | Hosted strict schema and documented no-training; local capacity handles exhausted tokens. Enable Groq only after ZDR/account limits are verified; minors/uncleared regions go local. Both must pass golden set. [G1 · 2026-10-11] [G3 · 2026-10-11] [G4 · 2026-10-11] [G5 · 2026-10-09] [L1 · 2026-10-11] |
| Text: round 3 feedback, suggestions | Local Qwen → Groq only with reserved free headroom → queue | Preserve hosted allowance for gist/key points. Templates for rounds 1–2 while saving mode is on; implementation details in #64. |
| Speech assessment | Self-hosted composite from #20/#21 → optionally Azure PA for supported measures → queue/unavailable | Preserve local voice processing; Azure is eligible but tiny free pool and incomplete seven-measure coverage. No activation before quality, license, latency, consent and mapping gates. [P1 · 2026-10-11] [P2 · 2026-10-11] [A4 · 2026-10-11] [A5 · 2026-10-11] |
| Transcription | Existing `faster-whisper` only | Keep ADR 0028/#18; no hosted fallback initially. |
| Alignment | Existing `wav2vec2-ctc` only, pending #19/license review | Keep ADR 0028; MMS_FA is no-training eligible locally but not approved for commercial use. [T3 · 2026-10-11] |

These are selected directions with deployment gates, not claims that the unimplemented adapters are ready. ADR [0034](../adr/0034-free-ai-provider-order-and-eligibility.md) records the decision. #64 adds the runtime IDs, eligibility checks, per-task order, quotas, provenance, schemas and admin usage view. This PR proposes the order in its description and does not edit `ai.yaml`.

## Sources

Only official provider/maintainer sources below were used for provider facts. Each inline reference embeds its read date and resolves directly to the URL. An unconfirmed statement identifies the closest source checked, without pretending the page supports the missing fact.

| Provider / project | Official sources (date read in each link) |
| --- | --- |
| Groq | [G1 · 2026-10-11] limits; [G2 · 2026-10-11] models/prices; [G3 · 2026-10-11] data controls; [G4 · 2026-10-11] services agreement; [G5 · 2026-10-09] schema output; [G6 · 2026-10-09] OpenAI compatibility |
| Mistral | [M1 · 2026-10-09] limits; [M2 · 2026-10-09] commercial terms; [M3 · 2026-10-09] privacy; [M4 · 2026-10-09] API; [M5 · 2026-10-09] prices |
| Gemini | [GE1 · 2026-10-09] prices; [GE2 · 2026-10-09] limits; [GE3 · 2026-10-09] terms; [GE4 · 2026-10-09] structured output |
| Cerebras | [C1 · 2026-10-11] trial/limits; [C2 · 2026-10-11] prices; [C3 · 2026-10-09] terms; [C4 · 2026-10-09] privacy; [C5 · 2026-10-09] structured output |
| OpenRouter / GitHub | [O1 · 2026-10-11] plans; [O2 · 2026-10-11] terms; [O3 · 2026-10-09] schemas; [O4 · 2026-10-09] rate limits; [GH1 · 2026-10-11] retirement |
| Local text | [L1 · 2026-10-11] Ollama artifact; [L2 · 2026-10-11] schemas; [L3 · 2026-10-09] API; [L4 · 2026-10-09] Ollama license; [L5 · 2026-10-11] Qwen model card; [L6 · 2026-10-09] llama.cpp server; [L7 · 2026-10-09] license; [L8 · 2026-10-09] Phi model; [L9 · 2026-10-09] Gemma terms |
| Local speech | [P1 · 2026-10-11] #20 quality/model spike; [P2 · 2026-10-11] #21 latency spike; [S1 · 2026-10-11] GOPT maintainer; [T1 · 2026-10-11] faster-whisper; [T2 · 2026-10-11] Whisper; [T3 · 2026-10-11] exact MMS_FA bundle/license |
| Azure Speech | [A1 · 2026-10-09] prices; [A2 · 2026-10-09] quotas; [A3 · 2026-10-09] PA behavior; [A4 · 2026-10-11] model-improvement policy; [A5 · 2026-10-11] privacy; [A6 · 2026-10-11] regions; [A7 · 2026-10-11] product terms |
| Speechace | [SA1 · 2026-10-11] plans; [SA2 · 2026-10-11] API privacy; [SA3 · 2026-10-11] API terms; [SA4 · 2026-10-11] trial checkout |
| SpeechSuper | [SS1 · 2026-10-11] prices; [SS2 · 2026-10-11] privacy; [SS3 · 2026-10-11] terms; [SS4 · 2026-10-11] trial |
| Deepgram | [D1 · 2026-10-11] prices; [D2 · 2026-10-11] limits; [D3 · 2026-10-11] data controls; [D4 · 2026-10-11] opt-out pricing change; [D5 · 2026-10-11] terms |

[G1 · 2026-10-11]: https://console.groq.com/docs/rate-limits
[G2 · 2026-10-11]: https://console.groq.com/docs/models
[G3 · 2026-10-11]: https://console.groq.com/docs/your-data
[G4 · 2026-10-11]: https://console.groq.com/docs/legal/services-agreement
[G5 · 2026-10-09]: https://console.groq.com/docs/structured-outputs
[G6 · 2026-10-09]: https://console.groq.com/docs/openai
[M1 · 2026-10-09]: https://docs.mistral.ai/admin/billing-usage/usage-limits
[M2 · 2026-10-09]: https://legal.mistral.ai/terms/commercial-terms-of-service/
[M3 · 2026-10-09]: https://legal.mistral.ai/terms/privacy-policy/
[M4 · 2026-10-09]: https://docs.mistral.ai/api
[M5 · 2026-10-09]: https://mistral.ai/pricing/api/
[GE1 · 2026-10-09]: https://ai.google.dev/gemini-api/docs/pricing
[GE2 · 2026-10-09]: https://ai.google.dev/gemini-api/docs/rate-limits
[GE3 · 2026-10-09]: https://ai.google.dev/gemini-api/terms
[GE4 · 2026-10-09]: https://ai.google.dev/gemini-api/docs/structured-output
[C1 · 2026-10-11]: https://inference-docs.cerebras.ai/support/rate-limits
[C2 · 2026-10-11]: https://www.cerebras.ai/pricing
[C3 · 2026-10-09]: https://cloud.cerebras.ai/terms
[C4 · 2026-10-09]: https://www.cerebras.ai/privacy-policy
[C5 · 2026-10-09]: https://inference-docs.cerebras.ai/capabilities/structured-outputs
[O1 · 2026-10-11]: https://openrouter.ai/pricing
[O2 · 2026-10-11]: https://openrouter.ai/terms
[O3 · 2026-10-09]: https://openrouter.ai/docs/guides/features/structured-outputs
[O4 · 2026-10-09]: https://openrouter.ai/docs/api-reference/limits
[GH1 · 2026-10-11]: https://docs.github.com/en/github-models
[L1 · 2026-10-11]: https://ollama.com/library/qwen3:4b-instruct
[L2 · 2026-10-11]: https://docs.ollama.com/capabilities/structured-outputs
[L3 · 2026-10-09]: https://github.com/ollama/ollama/blob/main/docs/api/introduction.mdx
[L4 · 2026-10-09]: https://github.com/ollama/ollama/blob/main/LICENSE
[L5 · 2026-10-11]: https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
[L6 · 2026-10-09]: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
[L7 · 2026-10-09]: https://github.com/ggml-org/llama.cpp/blob/master/LICENSE
[L8 · 2026-10-09]: https://huggingface.co/microsoft/Phi-4-mini-instruct
[L9 · 2026-10-09]: https://ai.google.dev/gemma/terms
[P1 · 2026-10-11]: https://github.com/abubakar1010/ListenUp/issues/20
[P2 · 2026-10-11]: https://github.com/abubakar1010/ListenUp/issues/21
[S1 · 2026-10-11]: https://github.com/YuanGongND/gopt
[A1 · 2026-10-09]: https://azure.microsoft.com/en-us/pricing/details/speech/
[A2 · 2026-10-09]: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-quotas-and-limits
[A3 · 2026-10-09]: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-pronunciation-assessment
[A4 · 2026-10-11]: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-encryption-of-data-at-rest
[A5 · 2026-10-11]: https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/speech-service/speech-to-text/data-privacy-security
[A6 · 2026-10-11]: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/regions
[A7 · 2026-10-11]: https://www.microsoft.com/licensing/terms/productoffering/MicrosoftAzure/allprograms
[SA1 · 2026-10-11]: https://www.speechace.com/api-plans/
[SA2 · 2026-10-11]: https://www.speechace.com/api-privacy-policy/
[SA3 · 2026-10-11]: https://www.speechace.com/api-terms-of-service/
[SA4 · 2026-10-11]: https://shop.speechace.com/subscription/signup-api/speechace-for-developers/speechace_api_2024_basic
[SS1 · 2026-10-11]: https://www.speechsuper.com/pricing.html
[SS2 · 2026-10-11]: https://www.speechsuper.com/privacy.html
[SS3 · 2026-10-11]: https://www.speechsuper.com/terms.html
[SS4 · 2026-10-11]: https://www.speechsuper.com/free-trial.html
[D1 · 2026-10-11]: https://deepgram.com/pricing
[D2 · 2026-10-11]: https://developers.deepgram.com/reference/api-rate-limits
[D3 · 2026-10-11]: https://developers.deepgram.com/trust-security/your-data
[D4 · 2026-10-11]: https://developers.deepgram.com/changelog/2026/3/5
[D5 · 2026-10-11]: https://deepgram.com/terms
[T1 · 2026-10-11]: https://github.com/SYSTRAN/faster-whisper
[T2 · 2026-10-11]: https://github.com/openai/whisper
[T3 · 2026-10-11]: https://docs.pytorch.org/audio/stable/generated/torchaudio.pipelines.MMS_FA.html
