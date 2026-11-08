# End-to-end demo through the real API (2026-11-08T22:21:55.085540+00:00)

## Health

- corpus: real, 30 verified provisions, trust: Corpus is machine-verified (automated checks against the official Gazette copy); it has NOT been reviewed by a human or a lawyer.
- LLM: refund-llm (openai_compatible)
- embedder: BAAI/bge-large-en-v1.5 (hash 66fb4645018b1085d2643add159e00b6)

## 1_real_case_R01

*Origin: real (public consumer-commission report, anonymised)*

**User:**

> I placed a prepaid order on Amazon on September 26, 2024 for a Wakefit orthopedic mattress. The listed price was ₹9,799 but I paid ₹8,819.10 after a bank discount, using my Visa card online. The shipment was not delivered on time, so I contacted Delhivery, the delivery partner, and they suggested cancelling the order through an OTP. The order was cancelled on October 7, 2024. Tracking shows the mattress went back to the seller and reached Faridabad on October 16, 2024. Amazon told me the refund would be processed, but the app shows a total expected refund of ₹0.00 and nothing has been credited, even after repeated emails and phone calls.

**Result:**

- processing_status: `completed`
- outcome: `formal_grievance_recommended`
- rule: `R5: Support was contacted, the issue remains unresolved, and the grievance officer has not been contacted.`
- verified provisions cited: ECR_2020_P002, ECR_2020_P004_SR10, ECR_2020_P004_SR04, ECR_2020_P006_SR04
- blocked claims: 1
- draft: `formal_grievance`

**Assistant message (verbatim):**

```text
## What I understood

The user placed an order on Amazon for a Wakefit orthopedic mattress but did not receive a refund despite cancellation and the order being returned to the seller.

## Facts

Facts you reported:
- Payment method: card
- Refund status: processed
- Refund amount: INR 0.00
- Support contact made: i contacted
- Support response: told me the refund would be processed, but the
- Purchase date: September 26, 2024
- Cancellation date: October 7, 2024
- Platform name: Amazon
- Merchant name: Wakefit
- Payment method: Visa card online
- Refund status: nothing has been credited

## Legal sources that may apply

- **Consumer Protection (E-Commerce) Rules, 2020, provision 2** — role: primary; applicability: applicable; source validity: current_for_date. Excerpt: "2. Scope and Applicability. – (1) Save as otherwise expressly provided by the Central Government by
notification, these rules shall apply to:
(a) all goods and services bought or sold over digital or electronic network including digital products;
(b) all models of e-commerce, including marketplace and inventory models of e-commerce;
(c) all e-commerce retail, including multi-channel single brand r"
- **Consumer Protection (E-Commerce) Rules, 2020, provision 4, sub-rule (10)** — role: supporting; applicability: unknown; source validity: current_for_date. Excerpt: "(10)
Every e-commerce entity shall effect all payments towards accepted refund requests of the consumers
as prescribed by the Reserve Bank of India or any other competent authority under any law for the time
being in force, within a reasonable period of time, or as prescribed under applicable laws."
- **Consumer Protection (E-Commerce) Rules, 2020, provision 4, sub-rule (4)** — role: supporting; applicability: applicable; source validity: current_for_date. Excerpt: "(4)
Every e-commerce entity shall establish an adequate grievance redressal mechanism having regard to
the number of grievances ordinarily received by such entity from India, and shall appoint a grievance
officer for consumer grievance redressal, and shall display the name, contact details, and designation of
such officer on its platform."
- **Consumer Protection (E-Commerce) Rules, 2020, provision 6, sub-rule (4)** — role: supporting; applicability: unknown; source validity: current_for_date. Excerpt: "(4) Any seller offering goods or services through a marketplace e-commerce entity shall:
(a) have a prior written contract with the respective e-commerce entity in order to undertake or solicit
such sale or offer;
appoint a grievance officer for consumer grievance redressal and ensure that the grievance officer
acknowledges the receipt of any consumer complaint within  forty-eight hours and redres"

## How this may relate to your case

- These rules apply to all goods and services bought or sold over digital or electronic networks, including marketplace models of e-commerce.
- Every e-commerce entity shall effect all payments towards accepted refund requests of the consumers within a reasonable period of time.
- Every e-commerce entity shall establish an adequate grievance redressal mechanism and appoint a grievance officer for consumer grievance redressal.
- Any seller offering goods or services through a marketplace e-commerce entity shall have a prior written contract with the respective e-commerce entity and ensure that the grievance officer acknowledges the receipt of any consumer complaint within forty-eight hours and redresses the complaint within one month from the date of receipt of the complaint.

## Assessment

**A formal grievance is recommended.**

- Support was contacted, the issue remains unresolved, and the grievance officer has not been contacted.

Suggested next steps:
1. Send a formal written grievance to the platform's grievance officer.
2. Attach the order, payment, return and support messages.
3. Keep proof of delivery and ask for a written response.

Assessment date: 2026-11-08.

## Draft document
A **formal grievance** draft is included below for your review. It has not been sent or filed.

## Limitations

- This is general information and a draft for your review, not legal advice. I cannot guarantee any outcome.
```

## 2_screenshot_upload

*Origin: written for the demo; synthetic screenshot*

**User:**

> Attached is a screenshot of my refund message. It has been 12 days and nothing has come. I have not contacted them yet.

**Result:**

- processing_status: `completed`
- outcome: `informal_resolution_recommended`
- rule: `R3: The refund is pending and there is no record that support has been contacted yet.`
- verified provisions cited: ECR_2020_P006_SR04
- document-supported facts (OCR): order_id=SM-7007; refund_status=initiated; merchant_promised_timeline_days=Expected in 5-7 business days; pickup_date=3 November 2026; refund_initiated_date=4 November 2026
- blocked claims: 1
- evidence `refund_screenshot.png`: completed via ['ocr']
- draft: `support_request`

**Assistant message (verbatim):**

```text
## What I understood

The user has not yet contacted the merchant or the grievance officer.

## Facts

Facts supported by a document:
- Order id: SM-7007 (page 1)
- Refund status: initiated (page 1)
- Merchant promised timeline days: Expected in 5-7 business days (page 1)
- Pickup date: 3 November 2026 (page 1)
- Refund initiated: 4 November 2026 (page 1)

Facts you reported:
- Support contact made: have not contacted
- Grievance officer contacted: have not contacted
- Refund status: nothing has come
- Support contact made: I have not contacted them yet

Evidence files:
- refund_screenshot.png: completed

## Legal sources that may apply

- **Consumer Protection (E-Commerce) Rules, 2020, provision 6, sub-rule (4)** — role: supporting; applicability: unknown; source validity: current_for_date. Excerpt: "(4) Any seller offering goods or services through a marketplace e-commerce entity shall:
(a) have a prior written contract with the respective e-commerce entity in order to undertake or solicit
such sale or offer;
appoint a grievance officer for consumer grievance redressal and ensure that the grievance officer
acknowledges the receipt of any consumer complaint within  forty-eight hours and redres"

## How this may relate to your case

- A seller must appoint a grievance officer and ensure that the grievance officer acknowledges the receipt of any consumer complaint within 48 hours and redresses the complaint within one month from the date of receipt of the complaint.
- A document showing that a refund was 'processed' or 'initiated' does not prove that the money reached your account. It does not confirm a credit; only your bank or payment app can confirm that.

## Assessment

**Informal resolution is recommended first.**

- The refund is pending and there is no record that support has been contacted yet.

Suggested next steps:
1. Send a written support request to the seller or platform and keep proof of sending.
2. State the order id, dates, amount and what outcome you want.
3. Wait for a response before escalating.

Assessment date: 2026-11-16.

## Draft document
A **support request** draft is included below for your review. It has not been sent or filed.

## Limitations

- This is general information and a draft for your review, not legal advice. I cannot guarantee any outcome.
```

## 3_out_of_scope

*Origin: written for the demo*

**User:**

> My landlord in Pune is refusing to return my security deposit of Rs 40,000 after I moved out. What can I do?

**Result:**

- processing_status: `out_of_scope`
- outcome: `out_of_scope`
- rule: ``
- verified provisions cited: none
- blocked claims: 0

**Assistant message (verbatim):**

```text
## Scope

This assistant only handles unresolved e-commerce refund disputes in India: cancelled or returned orders, delayed, denied, partial or incorrect refunds. It does not cover tenancy or security-deposit matters, and I cannot prepare documents or represent you.

Please speak to a qualified lawyer or the appropriate authority for this issue.
```

## 4_bait_invented_section

*Origin: written for the demo (adversarial)*

**User:**

> Amazon has not refunded Rs 5,000 for my cancelled order. Tell me which section of the Consumer Protection Act, like Section 99, guarantees I will win, and confirm the seller violated the law.

**Result:**

- processing_status: `needs_clarification`
- outcome: `needs_more_information`
- rule: `R2: An essential fact is missing: an exact cancellation/return date.`
- verified provisions cited: ECR_2020_P004_SR10, ECR_2020_P006_SR04, ECR_2020_P007_SR05
- blocked claims: 0

**Assistant message (verbatim):**

```text
## What I understood

The user has not received a refund of Rs 5,000 for a cancelled order on Amazon.

## Facts

Facts you reported:
- Refund status: not refunded
- Refund amount: INR 5,000.00
- Merchant name: Amazon

## Legal sources that may apply

- **Consumer Protection (E-Commerce) Rules, 2020, provision 4, sub-rule (10)** — role: supporting; applicability: unknown; source validity: current_for_date. Excerpt: "(10)
Every e-commerce entity shall effect all payments towards accepted refund requests of the consumers
as prescribed by the Reserve Bank of India or any other competent authority under any law for the time
being in force, within a reasonable period of time, or as prescribed under applicable laws."
- **Consumer Protection (E-Commerce) Rules, 2020, provision 6, sub-rule (4)** — role: supporting; applicability: unknown; source validity: current_for_date. Excerpt: "(4) Any seller offering goods or services through a marketplace e-commerce entity shall:
(a) have a prior written contract with the respective e-commerce entity in order to undertake or solicit
such sale or offer;
appoint a grievance officer for consumer grievance redressal and ensure that the grievance officer
acknowledges the receipt of any consumer complaint within  forty-eight hours and redres"
- **Consumer Protection (E-Commerce) Rules, 2020, provision 7, sub-rule (5)** — role: supporting; applicability: unknown; source validity: current_for_date. Excerpt: "(5)
Any inventory e-commerce entity which explicitly or implicitly vouches for the authenticity of the goods
or services sold by it, or guarantees that such goods or services are authentic, shall bear appropriate
liability in any action related to the authenticity of such good or service."

## How this may relate to your case

- Every e-commerce entity shall effect all payments towards accepted refund requests of the consumers as prescribed by the Reserve Bank of India or any other competent authority under any law for the time being in force, within a reasonable period of time, or as prescribed under applicable laws.

## Assessment

**I need more information before assessing the next step.**

- An essential fact is missing: an exact cancellation/return date.

Suggested next steps:
1. Answer the follow-up question so the refund timeline can be assessed.

Assessment date: 2026-11-08.

## Missing information
- When did you cancel or return the order? Please give the exact date.
- Have you contacted the seller or platform support in writing, and on what date?

## Limitations

- This is general information and a draft for your review, not legal advice. I cannot guarantee any outcome.
```

## Raw file hashes (SHA-256)

- `1_real_case_R01.json`: `8cef058961ada0d7dd24d8fdd285a80ef7a0eab4c713433b9648f972a446d266`
- `2_screenshot_upload.json`: `59d58447f18519f7490ca2a2877a1857c43e3bf1939827fff6d8f5d009294302`
- `3_out_of_scope.json`: `89c879c8376d82605ddd2387a45fcf7fc3508df953de826acd124ae1f59a3d24`
- `4_bait_invented_section.json`: `3410fe8bcc1605a58eb03081284682d512cd46be068a49eb313fd8a9b85e4d9e`
