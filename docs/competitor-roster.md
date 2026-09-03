# AssemblyAI Voice Agent Hackathon — public team roster

Captured 1 September 2026 (day 1) from the public teams list on
https://lablab.ai/ai-hackathons/assemblyai-voice-agent-hackathon

~250 teams registered. The great majority posted no idea at all ("still
deciding", "mew mew mew", "TestTest", "building something useful"). Listed
below are only the teams that stated a real, specific product — those are the
only ones that constitute competition.

---

## A. Operations / incident response (closest to our space)

**OdishaAI_Titans — OpsVoice AI**
Autonomous voice incident commander for SRE and DevOps. Inspect Kubernetes
clusters, troubleshoot crashed containers by voice, trigger self-healing
restarts, generate outage post-mortems. Voice Agent API + WebSockets.

**Himaless — IncidentBridge AI**
Evidence-backed voice incident commander for engineering/ops. Transcribes live
incident calls, identifies decisions/risks/action items, speaks up when a
critical task has no owner or deadline or conflicts with a previous decision.
Every insight links to exact speaker and timestamp. Explicitly: "Reliability,
security, and a polished demo matter more than feature count."

**Talos Tech — FieldNote**  ← DIRECT COMPETITOR
"Voice-first field operations platform that turns natural spoken reports into
structured, actionable workflows. Field workers can report incidents,
inspections and maintenance needs while on site. FieldNote extracts key
details, **identifies missing information**, assigns tasks to the appropriate
team member and tracks each report through acknowledgement and resolution.
Mobile-first field teams across facilities, energy, construction, agriculture."

**CHASK AI**
Voice-first coordination agent for residential construction and property
management. Supervisors report issues via WhatsApp with voice, text, photos.
Structures each incident, resolves the property, routes to the right
contractor, tracks repairs and reinspection. Solo.

**Voice Orbit**
AI voice assembly assistant guiding and automating complex assembly workflows
in real time.

**IsoCue**  ← ADJACENT, SAME MECHANISM
"Hands-free challenge-response system that helps industrial maintenance teams
capture stronger evidence that an approved lockout/tagout procedure was
followed. It **detects omissions**, validates physical isolation-point codes and
requires authenticated human verification — without allowing AI to declare
machinery safe."

**OpsCore AI — ArchitectVoice**
Voice-driven backend engineering assistant.

**SafarSync**
Voice copilot for vehicle owners: fuel, expenses, maintenance, receipts. Solo.

---

## B. Trust / verification / refusal (our mechanism, other domains)

**Voice Action Gate**  ← SAME CORE IDEA, DIFFERENT DOMAIN
"An irreversible action (a transfer, a refund) can only execute when the
transcript evidence is strong enough to mint a one-time confirmation
credential. When the agent can't tell what was said, **there is no code path to
'go ahead'** — it asks again." Solo.

**TRACE**  ← STRONGEST NARRATIVE IN THE FIELD
Voice agent for humanitarian field workers. Case note by speech in English or
French, structured into referral fields, "**marks what it cannot support
instead of filling it in**". "In a protection case a confident wrong summary is
worse than no summary at all, because a confident summary gets acted on and an
empty field gets checked." Abstains when confidence is low.

**ALERUNO Voice Assurance**
Turns spoken instructions into safe, verifiable actions. Preserves original
intent through agent decisions, verifies authorization before sensitive
actions, supports interruption and recovery, produces evidence of what was
requested / approved / executed / blocked. Solo.

**brute**
Deterministic deployment authorization gate for AI coding agents.

**VoiceGuard**
Zero-trust compliance gateway for enterprise AI voice pipelines: real-time PII
redaction, SHA-256 cryptographic audit logging.

**ASH**
Compliance and risk listener for regulated industries (finance, healthcare,
insurance, debt collection). Flags in real time when a speaker violates
compliance rules.

**Team TLE — VoiceFirewall**
Real-time safety layer for live calls: scam behaviour, social engineering,
urgency pressure, impersonation, credential requests. Live risk timeline,
"antivirus for conversations".

**Tech Titans**
Threat-call detection: analyses phone conversations for threatening, abusive or
suspicious language.

**FearUkaam — VIGIL**
Voice-first cybersecurity incident investigator. Reconstructs what happened,
asks follow-up questions, generates structured incident timeline and report.

**Countersign**
"Voice agent for security. Full concept revealed at submission."

---

## C. Reception / booking / small-business front desk (very crowded)

**Koeva — ReceptionAI** — virtual front desk for clinics and small businesses;
answers calls, checks calendar, books/reschedules/cancels, SMS/email confirm.

**Techie Tacos — DukaanOS** — "AI voice employee" for small businesses:
answers questions, qualifies leads, takes orders, schedules appointments,
business-specific knowledge base.

**RevenueFlow** — WhatsApp voice note → booked appointment in ~7 seconds,
Spanish/Portuguese, Latin America. Universal-3.5 Pro biased with the business's
service catalog + LLM Gateway against a strict schema. "The model decides what
the customer wants, the system decides what's allowed." **Already live** at
revenueflow-ai-yanero.vercel.app

**Mustafa Bin Tariq** — post-service quality verification calls, sentiment
capture, CRM integration.

**CloseLoop AI** — outbound sales, inbound calls, website chat, sales coaching.

**Eva**, **VoiceAura**, **Nemo AI**, **akmlxfzy**, **Team Solo**, **CallLens AI**
— generic call-centre / customer-conversation automation.

---

## D. Healthcare

**ByteForce** — emergency voice assistant; gathers symptoms, retrieves from a
synthetic patient database, sends a structured brief to a mock hospital
dashboard before the patient arrives.

**VocalPulse** — voice-first clinical documentation and meeting summaries.

**healthesphere**, **The Lone Synapse**, **Medanova** — health tech, unspecified.

---

## E. Learning / coaching / practice

**SpeakQuest** — adaptive language coach, realistic voice situations,
pronunciation and fluency feedback, personalised curriculum.

**Prep Talk AI** — voice-first mock interview coach; clarity, structure, filler
words.

**Sonettra** — spatial computing coach, 3D avatars, board meetings / VC
pitches / behavioural interviews, exposure therapy for executive presence.

**BlaBlaBla — Read-Along** — listens to a kid read out loud.

---

## F. Accessibility / inclusion / translation

**the oddessy** — voice-first AI agent on any basic feature phone, no
smartphone or internet needed. ~2.2B people offline worldwide, ~250M in India.
Farming and agri-knowledge first, extensible to health and government. Real
tool calling: checking info, booking tickets, making payments.

**KalkiAI Voice Agent** — real-time voice translation plus clarity for users
with hearing difficulty.

**Listen to one ear** — language translation.

**Konthora Voice Lab** — privacy-conscious multilingual agent, timestamped
transcripts with export options.

**URKU** — voice guide for tourists at cultural heritage sites, Arequipa first.

**Project Suara** — AI memoir services for Malaysia's aging generations.

**cubiczan — EVERCALL** — "Jarvis for Grandma": daily warm phone call to
elderly parents, med nudges, mood via sentiment analysis, missed meds, memory
slips, diarization spots when a caregiver joins, family dashboard. Explicitly
positioned against "everyone else builds meeting notetakers". Squad of 4.

---

## G. Technical / infrastructure demos (no domain)

**TurnWise AI** — full-duplex interruption-aware agent; distinguishes a genuine
interruption from a backchannel, decides when to yield vs keep talking.

**VoiceForge** — cascaded agent with paralinguistic side-channel, turn-taking,
backchannelling, benchmarked on τ-Voice.

**Hyperdrift — Bridge Voice** — intelligent endpointing as the trigger: the
moment your sentence lands it fires a real MCP tool call against a production
fleet. "No mock data, no staged demo — a live sandbox anyone can try."

**NeuraCall** — offline-first multi-device agent that wirelessly hijacks
physical smartphones to handle real cellular and WhatsApp calls.

**Endpointing** — "production-grade voice agent on AssemblyAI's Voice Agent
API. Full-stack and applied AI background, committed for the full month.
Looking for a frontend dev and someone with domain knowledge in a real industry
problem."

**Speechit**, **Zeroshot**, **BU-TS** — building their own STT/TTS models.

---

## H. Content / media / data

**Ninjas — STICK** — spoken ideas into editable presentations.
**VibeMarketing Studio — Viral Studio** — voice-directed AI cinema engine.
**DataWhisperer** — CSV → Plotly visualisations + spoken executive briefings.
**VOICEREACH** — live Twitter/Reddit/YouTube consensus + research briefings.
**Creator Sidecar** — AI sidecar for content creators.
**WattWise** — energy market data assistant.
**Thirty AI** — financial voice infrastructure.
**Dev-Hack — Agri-Fresh** — spoilage reduction supply chain for farmers.
**PratiDhwani** — faster disaster prevention.
**Echooooo** — personal agent with long-term memory.
**House of Voices** — AI companion app, characters with own voices.
**Webda VoiceOps** — voice agent for Discord.
**Space Cats** — single communication system for an entire workforce.

---

## Signal summary

- **~250 registered, roughly 60 with a stated product.** Most of the roster is
  noise on day one; the real field is far smaller than the headline number.
- **Two crowded clusters:** reception/booking bots and generic
  "call-centre automation". At least a dozen teams in each. Anyone landing
  there is invisible.
- **The refusal/verification mechanism is NOT unique to us.** Voice Action
  Gate, TRACE, ALERUNO, IsoCue and brute are all building "the agent must not
  proceed without evidence". This was our headline differentiator and it is
  contested.
- **Field service is contested but not crowded.** Talos Tech (FieldNote) is a
  direct competitor with nearly our exact framing, including "identifies
  missing information".
- **At least one team is already live in production** (RevenueFlow) on day one.
