Yes. Your clarification changes the engineering recommendation substantially.

The previous answer was still too anchored to the **old report's proposed architecture**. For this semester, I would treat the report as the **approved project concept**, but design the implementation as a **new, coherent software system** around that concept.

And since your teammate already has the **intent model and sentiment/semantic model trained**, we should **not redesign those models**. We should make them clean, replaceable services inside the application.

The important principle is:

> **Design the system boundaries first, then plug the existing models into those boundaries.**
>
> That prevents the classic problem where the frontend, backend, database and ML code are independently built and don't fit together at the end.

I reviewed the report again, particularly the architecture, message flow, AI pipeline, implementation sections and future scope. The core concept is consistently described as channel ingestion → identity resolution → unified conversation → AI enrichment → compliance → agent interaction. UnifyComm_G16_Sem6_Report (3)

# 1. First, forget the old UI

I would **not** say:

> "The final project should be an agent dashboard with three panels."

That was only one possible presentation.

Instead, think of UnifyComm as a **backend communication and intelligence platform with a web application on top of it**.

The actual product is:

> **A unified customer-interaction platform that ingests messages from multiple communication channels, identifies the customer, associates messages with the correct conversation, enriches every incoming message with AI-generated metadata, gives agents tools to understand and respond to the conversation, and applies policy/compliance checks before outbound communication.**

That is the project.

The UI can evolve independently.

---

# 2. The final system I recommend

This is the architecture I would actually approve as a lead engineer.

```text
                         ┌──────────────────────┐
                         │      CHANNELS        │
                         │                      │
                         │ WhatsApp             │
                         │ Email                │
                         │ SMS                  │
                         │ Demo / Simulator     │
                         └──────────┬───────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │    CHANNEL ADAPTER      │
                       │                         │
                       │ Normalize every channel │
                       │ into one message format │
                       └────────────┬────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │     MESSAGE INGESTION   │
                       │                         │
                       │ validate                │
                       │ deduplicate             │
                       │ persist                 │
                       │ acknowledge             │
                       └────────────┬────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │    IDENTITY RESOLVER    │
                       │                         │
                       │ phone/email/external ID │
                       └────────────┬────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │   CONVERSATION ENGINE   │
                       │                         │
                       │ customer → conversation │
                       │ conversation → messages │
                       └────────────┬────────────┘
                                    │
                                    ▼
                  ┌─────────────────┴─────────────────┐
                  │             AI LAYER              │
                  │                                   │
                  │  Intent Model                     │
                  │  Sentiment Model                  │
                  │  Priority / routing logic         │
                  │  Summarization                    │
                  │  Reply generation                 │
                  └─────────────────┬─────────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │       PostgreSQL        │
                       │                         │
                       │ customers               │
                       │ conversations           │
                       │ messages                │
                       │ AI results              │
                       │ agents                  │
                       │ consent                 │
                       │ compliance               │
                       └────────────┬────────────┘
                                    │
                         ┌──────────┴──────────┐
                         │                     │
                         ▼                     ▼
              ┌──────────────────┐   ┌──────────────────┐
              │   WEB APP        │   │   OUTBOUND       │
              │                  │   │   COMMUNICATION  │
              │ Agent UI         │   │                  │
              │ Conversations    │   │ Compliance       │
              │ Customer profile │   │ Channel adapter  │
              │ AI information   │   │ Provider API     │
              └──────────────────┘   └──────────────────┘
```

That is the system I'd build.

---

# 3. The single most important architectural decision

## **PostgreSQL is the source of truth.**

Not the frontend.

Not the AI models.

Not WhatsApp.

Not WebSocket.

Not the channel simulator.

Everything revolves around the database.

For example:

```text
Customer
   ↓
Conversation
   ↓
Messages
   ↓
AI metadata
   ↓
Agent actions
   ↓
Outbound messages
   ↓
Delivery status
```

The old report proposed PostgreSQL + pgvector + MongoDB. UnifyComm_G16_Sem6_Report (3)

I would **drop MongoDB**.

You gain nothing from introducing it here.

---

# 4. Build the backend as a modular monolith

I would also drop the idea of deploying many independent microservices.

Use:

```text
Next.js
    ↓
FastAPI
    ↓
PostgreSQL
```

with modules inside FastAPI.

For example:

```text
backend/
│
├── api/
│   ├── auth.py
│   ├── customers.py
│   ├── conversations.py
│   ├── messages.py
│   ├── agents.py
│   ├── ai.py
│   └── channels.py
│
├── services/
│   ├── message_service.py
│   ├── conversation_service.py
│   ├── identity_service.py
│   ├── compliance_service.py
│   ├── routing_service.py
│   └── outbound_service.py
│
├── ai/
│   ├── intent/
│   │   └── model.py
│   ├── sentiment/
│   │   └── model.py
│   ├── summarization/
│   │   └── service.py
│   └── reply/
│       └── service.py
│
├── channels/
│   ├── base.py
│   ├── simulator.py
│   ├── whatsapp.py
│   ├── email.py
│   └── sms.py
│
├── models/
│
├── schemas/
│
├── db/
│
└── workers/
```

This gives you **service boundaries without distributed-system pain**.

---

# 5. Your friend's two models fit into this very cleanly

This is where your new information matters.

Do **not** allow the rest of the project to directly import some random notebook/model code.

Create an interface.

For example:

```text
Incoming text
      ↓
AI Service
      ↓
Intent Model
```

The rest of the application should only care about the output.

### Intent model contract

```json
{
  "label": "card_payment_wrong",
  "confidence": 0.963
}
```

### Sentiment model contract

```json
{
  "label": "negative",
  "confidence": 0.941
}
```

Then the backend doesn't care whether your teammate's model is:

- MiniLM
- DistilBERT
- RoBERTa
- custom-trained transformer
- something else

That model is simply:

```text
Text → Prediction
```

This is critical.

Because otherwise six weeks later someone changes the model and breaks half the backend.

---

# 6. The model should be treated as a black box

This is the contract I'd give your AI coding agent:

```text
IntentPredictor

Input:
    text: string

Output:
    label: string
    confidence: float
```

and:

```text
SentimentPredictor

Input:
    text: string

Output:
    label: positive | neutral | negative
    confidence: float
```

The UI gets those outputs.

The database stores them.

The routing system can use them.

Nothing else needs to know how inference works.

---

# 7. I would NOT run AI inference directly inside the incoming HTTP request

This is another important correction.

Bad:

```text
WhatsApp
   ↓
API request
   ↓
Intent model
   ↓
Sentiment model
   ↓
Summarizer
   ↓
Database
   ↓
response
```

If a model takes 2 seconds, your webhook takes 2 seconds.

If the model crashes, message ingestion crashes.

Instead:

```text
CHANNEL
   ↓
INGEST
   ↓
SAVE MESSAGE
   ↓
return success
   ↓
AI PROCESSING
   ↓
update message
   ↓
WebSocket → UI
```

So:

```text
message.status

RECEIVED
   ↓
PROCESSING
   ↓
ENRICHED
```

This makes the system much harder to break.

---

# 8. The actual incoming-message lifecycle

Let's take:

> "I was charged twice for the same transaction."

### 1. WhatsApp/email/simulator sends message

```text
channel = whatsapp
external_message_id = abc123
sender = +91XXXXXXXXXX
text = "I was charged twice..."
```

### 2. Channel adapter converts it to your internal schema

Everything becomes:

```json
{
  "external_message_id": "abc123",
  "channel": "whatsapp",
  "sender_identifier": "+91XXXXXXXXXX",
  "text": "I was charged twice for the same transaction.",
  "timestamp": "...",
  "direction": "inbound"
}
```

This is the **channel abstraction** idea already present in your report. UnifyComm_G16_Sem6_Report (3)

### 3. Deduplication

Check:

```text
external_message_id = abc123
```

If already present:

```text
ignore
```

This is essential because external webhooks can be retried.

---

# 9. Identity resolution should NOT use aggressive fuzzy matching

Your report proposes fuzzy matching as a fallback. UnifyComm_G16_Sem6_Report (3)

I would change that.

For a real system, accidentally combining two customers is worse than creating a new conversation.

Use this order:

```text
1. verified phone number
2. verified email
3. external channel customer ID
4. explicit existing identity mapping
5. otherwise → unresolved customer
```

Not:

```text
"These two names look similar"
       ↓
merge customers
```

No.

Instead:

```text
Possible match found
       ↓
manual confirmation
```

This avoids catastrophic customer-data corruption.

---

# 10. Customer and conversation are different entities

This is another distinction that needs to be explicit.

A customer:

```text
Rahul Sharma
Phone
Email
```

can have:

```text
Conversation #104
Conversation #187
Conversation #221
```

For example:

```text
Rahul
 ├── Payment issue
 ├── Card issue
 └── Refund issue
```

You should **not** create one giant lifetime conversation.

Instead:

```text
Customer
   ↓
Conversation
   ↓
Messages
```

This makes the product much closer to a real support system.

---

# 11. Every message should have channel metadata

Example:

```text
Message
────────────────────
id
conversation_id
customer_id
channel
direction
sender_type
content
external_message_id
created_at
delivery_status
intent
intent_confidence
sentiment
sentiment_confidence
```

So the unified conversation can contain:

```text
WhatsApp → message
Email    → message
SMS      → message
```

without losing where each message came from.

---

# 12. Then the two existing AI models run

After persistence:

```text
Message
   │
   ├───────────────┐
   ↓               ↓
Intent          Sentiment
Model             Model
   │               │
   └───────┬───────┘
           ↓
      AI Metadata
```

Example:

```json
{
  "intent": {
    "label": "transaction_charged_twice",
    "confidence": 0.98
  },
  "sentiment": {
    "label": "negative",
    "confidence": 0.92
  }
}
```

Store this.

Now the AI result becomes part of the conversation record.

---

# 13. Routing should be deterministic

I would not let an LLM decide everything.

Example:

```text
Intent:
transaction_charged_twice
        ↓
Billing queue
```

```text
Intent:
card_lost
        ↓
Card Support
```

```text
Sentiment:
negative
        ↓
Priority = high
```

That's simple, explainable and reliable.

You don't need an "AI routing agent" just for the sake of saying it's AI.

---

# 14. Then you need an AI response layer

This should be separate from the two classification models.

```text
Conversation
     +
customer message
     +
conversation summary
     +
intent
     +
sentiment
     ↓
Reply Generator
     ↓
Draft response
```

Example:

```text
Customer:
"I was charged twice."

AI draft:

"I understand your concern. I can see that you're
reporting a duplicate transaction. Let me help you
check the transaction details and resolution status."
```

The agent can:

```text
Edit
Regenerate
Send
```

Do **not** automatically send the LLM's output.

---

# 15. Summarization should be separate too

Do not make the summarizer run for every message.

That's wasteful.

Instead:

```text
Conversation
      ↓
10 / 20 / N new messages
      ↓
Generate summary
```

or manually:

```text
Agent clicks "Summarize"
```

The old report already proposes configurable summarization intervals and on-demand summaries. UnifyComm_G16_Sem6_Report (3)

That idea is good.

---

# 16. The summary belongs to the conversation

Not the customer.

Example:

```text
Conversation #104

Summary:
Customer reports duplicate debit of ₹500.
Agent verified transaction ID.
Refund request has been initiated.
Customer is waiting for confirmation.
```

Next time an agent opens that conversation, this summary is available immediately.

---

# 17. Compliance should sit on the OUTBOUND path

This is extremely important.

Don't do:

```text
Message received
    ↓
Compliance
```

because compliance doesn't need to block ordinary inbound messages.

The meaningful location is:

```text
Agent
  ↓
Draft response
  ↓
SEND
  ↓
Compliance Engine
  ↓
ALLOW / BLOCK
  ↓
Channel Provider
```

The report itself describes compliance as a pre-outbound validation pipeline. UnifyComm_G16_Sem6_Report (3)

---

# 18. Compliance should be a pure rule engine

For the student implementation:

```text
Consent check
DND/DNC check
Allowed time check
Basic content policy
```

Output:

```json
{
  "allowed": false,
  "reason": "Customer has not granted WhatsApp consent"
}
```

or:

```json
{
  "allowed": true,
  "reason": null
}
```

This is much better than burying compliance logic throughout the code.

---

# 19. Your compliance database can be simulated

You do **not** need a government DND integration.

Have:

```text
customer_channel_preferences

customer_id
channel
consent_status
dnd_status
updated_at
```

Then your demonstration becomes real from the application's perspective.

Example:

```text
Rahul
WhatsApp
Consent: YES
DND: NO
```

→ message allowed.

```text
Priya
WhatsApp
Consent: NO
DND: NO
```

→ blocked.

That demonstrates the architecture without pretending to have real regulatory infrastructure.

---

# 20. Outbound communication also needs an adapter architecture

Exactly like inbound.

Don't write:

```text
if channel == "whatsapp":
    twilio.whatever()
elif channel == "email":
    smtp.whatever()
```

everywhere in your backend.

Use:

```text
ChannelProvider
      │
      ├── WhatsAppProvider
      ├── EmailProvider
      ├── SMSProvider
      └── SimulatorProvider
```

Each implements something like:

```text
send(message) → result
```

Now your application doesn't care whether the response went through:

```text
Twilio
SMTP
demo simulator
```

This is how you prevent later integration from becoming a mess.

---

# 21. The simulator is not a "fake feature"

I strongly recommend building it.

It's a **development and demonstration channel adapter**.

For example:

```text
POST /channels/simulator/messages
```

with:

```text
channel = whatsapp
sender = Rahul
message = ...
```

The rest of the system behaves exactly as if WhatsApp delivered it.

This is incredibly useful because now you can test the entire platform without depending on third-party APIs.

---

# 22. Then optionally plug in real WhatsApp

Once the simulator works:

```text
SimulatorProvider ──┐
                    │
WhatsAppProvider ───┼──→ MessageService
                    │
EmailProvider ──────┤
                    │
SMSProvider ────────┘
```

The core system doesn't change.

That is exactly what you want.

---

# 23. Real-time communication

Use WebSockets from backend → frontend.

Important distinction:

**WebSocket is not the data store.**

PostgreSQL remains the source of truth.

Flow:

```text
Message saved
     ↓
AI enriched
     ↓
Database updated
     ↓
WebSocket event
     ↓
Frontend updates
```

If the frontend disconnects:

```text
reconnect
   ↓
GET conversation
   ↓
database gives complete state
```

Nothing is lost.

That is much safer than relying on WebSocket events alone.

---

# 24. The frontend should therefore be a projection of backend state

This principle will save you a lot of trouble.

Frontend should not invent:

> "I think this conversation has 17 messages."

Backend says:

```text
Conversation #104
17 messages
```

Frontend displays it.

Likewise:

```text
intent
sentiment
summary
status
assignment
```

all come from backend APIs.

---

# 25. What the final application actually contains

Now we're at the important part.

Your finished product is essentially **five systems combined**.

## A. Communication Hub

Receives:

```text
WhatsApp
Email
SMS
Simulator
```

and converts them into a common message model.

---

## B. Conversation Management System

Maintains:

```text
customers
conversations
messages
agents
assignments
statuses
```

This is the operational core.

---

## C. AI Intelligence Layer

Existing models:

```text
Intent Model
Sentiment Model
```

plus:

```text
Summarization
Reply Generation
```

The report's AI architecture explicitly describes intent, sentiment, summarization and LLM-based drafting as distinct functions. UnifyComm_G16_Sem6_Report (3)

---

## D. Agent Workspace

The web interface where an agent can:

```text
see conversations
open customer
read history
see AI results
read summary
generate reply
edit reply
send response
```

---

## E. Policy / Compliance Layer

Before outbound communication:

```text
consent
DND/DNC
time rules
content rules
audit log
```

---

# 26. The final user experience

Forget the exact previous dashboard design.

The final application should let an evaluator do something like this:

### Step 1

Create/select:

```text
Customer: Rahul
```

### Step 2

Send:

```text
WhatsApp:
"My payment failed but the money was deducted."
```

### Step 3

System automatically:

```text
identifies Rahul
finds conversation
stores message
runs intent
runs sentiment
updates conversation
```

### Step 4

Agent opens the conversation.

They see:

```text
Conversation
──────────────

WhatsApp
"My payment failed but the money was deducted."

AI
Intent: payment_failed
Confidence: 96%

Sentiment: negative
Confidence: 94%

Priority: high
```

### Step 5

Rahul sends another message through **email**:

```text
"Any update?"
```

The system links it to the same conversation.

Now:

```text
Conversation #104

WhatsApp
10:31
My payment failed...

Email
10:42
Any update?
```

That is the central proof of UnifyComm.

---

# 27. Then AI assistance

Agent clicks:

```text
Generate response
```

The system uses:

```text
conversation
+
summary
+
latest message
+
intent
+
sentiment
```

to produce:

```text
Suggested Reply

"I understand your concern regarding the failed
payment and deducted amount. Let me check the
transaction status and assist you with the next steps."
```

Agent edits it.

---

# 28. Then compliance

Agent presses:

```text
Send
```

System:

```text
Consent        ✓
DND/DNC        ✓
Time window    ✓
Content rules  ✓

MESSAGE APPROVED
```

Then:

```text
EmailProvider.send()
```

or:

```text
WhatsAppProvider.send()
```

---

# 29. If the rule fails

Example:

```text
Consent        ✗
```

The actual provider is **never called**.

You get:

```text
MESSAGE BLOCKED

Reason:
Customer has not provided consent for WhatsApp
communication.
```

And:

```text
compliance_logs
```

gets a record.

That's a proper system rather than a UI trick.

---

# 30. What I would use technically

### Frontend

```text
Next.js
TypeScript
Tailwind CSS
```

### Backend

```text
FastAPI
Python
Pydantic
SQLAlchemy
Alembic
```

### Database

```text
PostgreSQL
```

### Real-time

```text
WebSocket
```

### AI

```text
PyTorch
Transformers
Existing intent model
Existing sentiment model
LLM for generation
```

### Infrastructure

```text
Docker Compose
.env configuration
```

Potentially:

```text
Redis
```

only when you actually need background job/queue functionality. I would **not add it on day one**.

---

# 31. What I would NOT use

For this project:

```text
❌ MongoDB
❌ Kafka
❌ Kubernetes
❌ multiple backend microservices
❌ separate databases for every module
❌ LangChain everywhere
❌ random AI agents deciding system state
❌ direct frontend → ML model calls
```

The goal is not to maximize technologies.

The goal is to create a **coherent system**.

---

# 32. Very important: the AI models must be packaged properly

Your friend's models should eventually become something like:

```text
models/
├── intent/
│   ├── config.json
│   ├── tokenizer/
│   └── weights/
│
└── sentiment/
    ├── config.json
    ├── tokenizer/
    └── weights/
```

plus a known inference wrapper.

The rest of the team should be able to run:

```text
predict_intent(text)
predict_sentiment(text)
```

without opening the training notebook.

That's the point at which a trained ML model becomes a usable **software component**.

---

# 33. Do not let Claude Code "improve" the models automatically

This is important.

Tell the AI agent:

> **The existing intent and sentiment models are authoritative project assets. Do not replace, retrain, modify, quantize, or substitute them unless explicitly instructed. Integrate them through the defined inference interfaces.**

Otherwise an AI coding agent may decide:

> "I'll just use a HuggingFace pretrained model instead."

And six weeks later your implementation no longer matches your actual work.

---

# 34. The exact API boundaries I'd define

You don't necessarily need all of these initially, but the architecture should be roughly:

```text
POST   /api/customers
GET    /api/customers/{id}

POST   /api/conversations
GET    /api/conversations
GET    /api/conversations/{id}

POST   /api/messages
GET    /api/conversations/{id}/messages

POST   /api/messages/{id}/analyze

POST   /api/conversations/{id}/summarize

POST   /api/conversations/{id}/generate-reply

POST   /api/conversations/{id}/send

GET    /api/customers/{id}/consents
PUT    /api/customers/{id}/consents

GET    /api/compliance/logs

POST   /api/webhooks/{channel}
```

And WebSocket:

```text
/ws/conversations/{conversation_id}
```

---

# 35. Events should also be standardized

For example:

```text
message.created
message.analyzed
message.updated

conversation.updated
conversation.assigned
conversation.summary_updated

reply.generated

message.send_requested
message.send_approved
message.send_blocked
message.sent
message.failed
```

Now the frontend knows exactly what events exist.

That prevents the frontend and backend teams from inventing incompatible event names later.

---

# 36. Database schema I would lock early

At minimum:

```text
users
agents

customers

customer_contacts
    phone
    email
    channel_identifier

conversations

conversation_participants

messages

message_ai_results

conversation_summaries

consents

compliance_rules
compliance_checks

outbound_messages

channel_accounts
```

You don't need to implement every table immediately, but the **relationships need to be settled before development gets serious**.

---

# 37. One subtle but important thing: outbound and inbound messages should be the same `messages` entity

Don't create:

```text
incoming_messages
outgoing_messages
```

Use:

```text
messages
```

with:

```text
direction = inbound | outbound
```

and:

```text
sender_type = customer | agent | system
```

Then your conversation is naturally chronological.

---

# 38. Another important thing: message status

For outgoing messages:

```text
DRAFT
    ↓
COMPLIANCE_PENDING
    ↓
APPROVED / BLOCKED
    ↓
SENDING
    ↓
SENT
    ↓
DELIVERED
    ↓
READ
```

You may only implement part of this, but establishing the state model prevents later redesign.

---

# 39. What happens if an AI model fails?

The application should **not stop working**.

For example:

```text
Message received ✓

Intent analysis
    ↓
ERROR
```

Conversation should still be available.

UI:

```text
Intent:
Unavailable
```

rather than:

```text
500 Internal Server Error
```

Likewise, if the LLM is unavailable:

```text
Generate Reply
     ↓
AI unavailable
```

but the agent can manually type and send.

This is what I mean by designing so that nothing breaks later.

---

# 40. What happens if WhatsApp is unavailable?

The rest of the system should continue working.

That's why:

```text
Channel Adapter
```

exists.

So:

```text
WhatsApp down
```

doesn't mean:

```text
UnifyComm down
```

The simulator still works.

The database still works.

The agent dashboard still works.

---

# 41. What should be real vs simulated?

This is the boundary I'd establish.

| Component | Final project |
|---|---|
| Customer data | **Real** |
| Conversations | **Real** |
| Message persistence | **Real** |
| Identity resolution | **Real** |
| Intent model | **Real — teammate's model** |
| Sentiment model | **Real — teammate's model** |
| AI summary | **Real** |
| AI reply generation | **Real** |
| WebSocket | **Real** |
| Compliance engine | **Real application logic** |
| Consent database | **Real application data** |
| DND/DNC registry | **Simulated/local** |
| WhatsApp | **Optional real integration** |
| SMS | **Simulator first** |
| Email | **Simulator first / optionally real** |
| Voice | **Not implemented** |
| RBI/TRAI infrastructure | **Not implemented** |
| Millions of users | **Not implemented** |

This is a very defensible scope.

---

# 42. What the actual "orchestration" means

The title can sound vague.

In your implementation, orchestration means:

```text
                MESSAGE
                   ↓
             Channel adapter
                   ↓
             Message service
                   ↓
           Identity resolution
                   ↓
           Conversation mapping
                   ↓
          ┌────────┴────────┐
          ↓                 ↓
       Intent           Sentiment
          └────────┬────────┘
                   ↓
                Priority
                   ↓
              Persist data
                   ↓
             Agent workspace
                   ↓
             Reply generation
                   ↓
              Compliance
                   ↓
             Channel adapter
                   ↓
              CUSTOMER
```

**That entire pipeline is the orchestration.**

---

# 43. The final project should therefore be described like this

This is the description I would give directly to Claude Code, Cursor, another coding agent, or a team member:

---

## UNIFYCOMM — FINAL ENGINEERING PROJECT DESCRIPTION

**UnifyComm is a modular AI-assisted omnichannel customer communication platform.**

The system provides a unified backend for handling customer interactions arriving from multiple communication channels such as WhatsApp, email, SMS, and an internal simulator. Every channel is implemented through an adapter that converts channel-specific messages into a common internal message schema.

When an inbound message is received, the system validates and deduplicates it, identifies the associated customer using reliable contact identifiers, and attaches the message to an appropriate support conversation. Customer identity and conversation state are persistent and independent of the communication channel, allowing messages from different channels to appear in the same conversation.

Every persisted inbound message can be asynchronously enriched by the AI layer. The AI layer contains two existing trained models supplied by the project team: an **intent classification model** and a **sentiment analysis model**. These models must be integrated through stable inference interfaces and must not be tightly coupled to the rest of the application. Their outputs, including predicted labels and confidence scores, are stored as structured message metadata.

The platform also provides conversation-level AI capabilities including automatic summarization and AI-assisted response generation. Summaries are generated on demand or according to configurable thresholds. Response generation uses the conversation history, current message, summary, intent and sentiment as context, and produces a draft for the human agent. AI-generated responses are never sent automatically; the agent can edit or reject the draft.

The web application provides an agent workspace for viewing customer conversations, customer information, complete cross-channel message history, AI analysis, summaries, suggested responses, conversation status and relevant operational information. Real-time updates are delivered through WebSockets, while PostgreSQL remains the authoritative source of application state.

Before any outbound message is transmitted, the message passes through a dedicated compliance/policy engine. The engine performs configurable checks such as customer consent, DND/DNC status, permitted communication time and basic content/policy rules. A failed check prevents transmission and creates an auditable compliance record. DND/DNC and consent information are represented using local application data for demonstration purposes rather than claiming integration with government regulatory systems.

Outbound communication is also adapter-based. The application sends through a channel abstraction so that the core system is independent of the specific provider. An internal simulator is implemented as a guaranteed development and demonstration channel, while real WhatsApp, email or SMS integrations may be added without changing the core conversation architecture.

The system is implemented as a **modular monolith** rather than a distributed microservice system. The recommended stack is Next.js and TypeScript for the frontend, FastAPI and Python for the backend and AI integration, PostgreSQL for persistent storage, WebSockets for real-time updates, and Docker Compose for local deployment. The architecture is designed so that individual channel providers and AI models can be replaced or added without changing the core conversation system.

The primary objective is to demonstrate a complete end-to-end workflow:

**multi-channel message ingestion → normalization → customer identification → conversation association → AI analysis → persistent storage → real-time agent interaction → AI-assisted response → compliance validation → outbound delivery.**

The project should prioritize correctness, modularity, explainability, fault tolerance and end-to-end integration over unnecessary enterprise infrastructure or excessive technology count.

---

# 44. And THIS is the mental picture you should have

Not:

> "We have a dashboard + two ML models."

Instead:

```text
                    UNIFYCOMM
                       │
       ┌───────────────┴────────────────┐
       │                                │
   COMMUNICATION                     INTELLIGENCE
       │                                │
 WhatsApp                             Intent
 Email                                Sentiment
 SMS                                  Summary
 Simulator                            Reply AI
       │                                │
       └───────────────┬────────────────┘
                       ↓
               CUSTOMER + THREAD
                       ↓
               AGENT WORKSPACE
                       ↓
              OUTBOUND RESPONSE
                       ↓
              POLICY / COMPLIANCE
                       ↓
                   CHANNEL
```

The **conversation system is the backbone**.

The AI models are intelligence attached to that backbone.

The channels are input/output adapters.

The compliance engine is a gate on the outbound path.

The frontend is simply how agents interact with the resulting system.

That separation is what will keep this project from turning into a pile of disconnected Claude-generated code.

---

# 45. Development order I would enforce

Do **not** let the team work in arbitrary feature order.

Build in this sequence:

```text
1. Database schema
          ↓
2. Backend domain models
          ↓
3. Message + conversation APIs
          ↓
4. Simulator channel
          ↓
5. Identity resolution
          ↓
6. Existing intent/sentiment models
          ↓
7. AI result persistence
          ↓
8. Frontend conversation UI
          ↓
9. WebSocket updates
          ↓
10. Summarization
          ↓
11. Reply generation
          ↓
12. Compliance
          ↓
13. Outbound simulator
          ↓
14. Real channel integration
          ↓
15. Analytics / polish
```

At the end of step 4, you already have a functioning communication system.

At step 7, you have a functioning **AI communication system**.

At step 13, you have the complete UnifyComm loop.

Everything after that is enhancement.

---

## The one thing I'd settle before anyone asks Claude Code to start

Create a **single `ARCHITECTURE.md` / engineering specification** containing the entities, database relationships, message schema, API contracts, AI model contracts, WebSocket event contracts, channel adapter interface and state transitions above.

Then every person—and every AI coding agent—works against that contract.

That is the strongest way to make sure **the model your friend already trained, the backend somebody else writes, the frontend you build, and the eventual WhatsApp/simulator integration all fit together instead of becoming separate projects.**