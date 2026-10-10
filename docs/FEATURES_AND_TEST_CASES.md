**Harbor Ledger: features and manual test cases**

This guide describes the current synthetic application, using the exact labels and example values in the dashboard. All records are fictional. Every successful workflow stops at a review screen. “Success” means the request is ready for review; it does not mean an account was opened, a card replaced, money refunded, an address changed, a statement sent, or a fee waived.

**How to run the two tests for each feature**

1. Open http://127.0.0.1:8766/ and refresh once if the dashboard code was recently updated.
2. Select the Banking workflow named below. Choose Discover with AI, Model provider = Gemini, and Test scenario = Normal workflow.
3. Enter every value in column A. The Member 10023 example button fills these values for you.
4. Click Discover and save. You do not demonstrate the steps on the banking website first. The agent uses the goal and current UI to decide the steps.
5. For a successful discovery, expect Run status = Success, model calls greater than zero, the correct review screen, matching input values in Result, review ready = true, and a new saved capability. Model-call counts and duration may vary.
6. Click Use this capability with new inputs. Check Replay capability is selected and the saved capability belongs to the same workflow.
7. Enter every value in column B, or click Member 10042. Keep Test scenario = Normal workflow. A model provider is not used for replay.
8. Click Run capability. Expect Success, all B values on the review/result, review ready = true, and exactly zero model calls. No new discovery is needed for that second member.

Test A checks model-guided discovery and creation of a reusable capability. Test B checks that the same capability accepts different inputs and completes without a model. If a capability is already saved, you may test B immediately. If no capability exists, B must wait for a successful A. Never use another workflow's capability.

A provider error is not a successful discovery: inspect Activity and Result. The previous address attempts received provider-unavailable responses. The checks below describe expected behavior, not a guarantee that a live provider will always respond.

**1. Sub-account review** — A member wants another Savings or Checking account, such as an Emergency Fund. The engine prepares the account request for staff review.

| Field | Meaning | A: discovery | B: replay |
|---|---|---|---|
| Member ID | Which customer to work with; this is a demo member number. | 10023 | 10042 |
| Product | Savings for setting money aside, or Checking for everyday transactions. | Savings | Checking |
| Account nickname | A friendly name for the requested account. | Emergency Fund | Travel Fund |

Expected screen: **Review sub-account**. All three input values match the review. No account is opened.

What these tests show: The saved steps work for another member, account type, and nickname.

**2. Card replacement** — A member has a damaged, lost, or stolen card. The engine finds that member's card and prepares replacement preferences.

| Field | Meaning | A: discovery | B: replay |
|---|---|---|---|
| Member ID | Which customer to work with; this is a demo member number. | 10023 | 10042 |
| Card reference | Which card belongs to this member; a demo record ID, not a full card number. | CARD-10023 | CARD-10042 |
| Replacement reason | Why the member wants a replacement card. | Damaged | Lost |
| Replacement delivery | Where the requested replacement would be collected or delivered. | Branch pickup | Registered address |

Expected screen: **Review card replacement**. Both tests show Card product = Everyday debit and Card standing = Active, along with the requested member, card, reason, and delivery. No card is blocked or replaced.

What these tests show: The engine locates the correct member-owned card and applies new preferences using the same saved steps.

**3. Transaction dispute** — A member questions a payment, for example because they were charged twice or did not receive a service. The engine prepares the information needed for an investigation.

| Field | Meaning | A: discovery | B: replay |
|---|---|---|---|
| Member ID | Which customer to work with; this is a demo member number. | 10023 | 10042 |
| Transaction reference | Which payment the member wants investigated. | TXN-10023 | TXN-10042 |
| Dispute reason | Why the member questions the payment. | Duplicate charge | Service not received |
| Contact channel | How staff would contact the member about the dispute. | Secure message | Phone |

Expected screen: **Review transaction dispute**. Both tests show Merchant = Harbor Market and Transaction status = Posted. Test A shows Transaction amount = USD 84.20; Test B shows USD 126.50. The requested reason and contact channel also match. No refund or dispute submission occurs.

What these tests show: The engine reads the selected transaction's details from the banking UI; replay returns the second transaction's amount rather than keeping the first amount.

**4. Address change** — A member wants to change their mailing address. The engine prepares the new address and the requested verification route.

| Field | Meaning | A: discovery | B: replay |
|---|---|---|---|
| Member ID | Which customer to work with; this is a demo member number. | 10023 | 10042 |
| Street address | The requested new street address. | 45 Market Street | 280 Pine Avenue |
| City | The requested new city. | San Francisco | Austin |
| State code | The two-letter state code; use uppercase letters. | CA | TX |
| Postal code | The five-digit postal code for this demo. | 94105 | 78701 |
| Verification method | How staff should verify the request: in branch or through a callback. This selection does not perform verification. | Branch verification | Callback verification |

Expected screen: **Review address change**. All new-address fields match the chosen test. Current mailing address is 123 Harbor Avenue in Test A and 142 Harbor Avenue in Test B; Current city is San Francisco and Contact standing is Verified in both. These current details are separate from the proposed new address. The stored address does not change.

What these tests show: The engine handles several related fields and distinguishes the current address from the proposed address. It does not verify a customer's identity itself.

**5. Statement request** — A member wants a statement: a document showing account activity for a chosen month. The engine prepares the account, month, format, and delivery request.

| Field | Meaning | A: discovery | B: replay |
|---|---|---|---|
| Member ID | Which customer to work with; this is a demo member number. | 10023 | 10042 |
| Account reference | Which existing account the statement is for. | ACC-10023 | ACC-10042 |
| Statement period | Which month the member wants; these are fixed demo periods. | September 2026 | August 2026 |
| Document format | A PDF document or a paper copy. | PDF | Paper copy |
| Document delivery | Delivery to a secure inbox or collection from a branch. | Secure inbox | Branch collection |

Expected screen: **Review statement request**. Both tests show Account product = Everyday checking and Document access = Available. The account, month, format, and delivery match the chosen test. No PDF is generated, printed, or sent.

What these tests show: The same saved workflow can locate another eligible account and prepare different document preferences.

**6. Fee adjustment** — A member asks staff to remove or reduce a fee. The engine finds the fee and prepares a review request with the reason and supporting note.

| Field | Meaning | A: discovery | B: replay |
|---|---|---|---|
| Member ID | Which customer to work with; this is a demo member number. | 10023 | 10042 |
| Fee reference | Which bank fee the member wants reviewed. | FEE-10023 | FEE-10042 |
| Adjustment reason | Why staff should consider changing the fee. | First occurrence | Service issue |
| Requested resolution | Full waiver asks to remove the whole fee; partial waiver asks to remove part of it. This does not approve either. | Full waiver | Partial waiver |
| Supporting note | A short explanation supporting the fee-review request. | First fee review requested by member | Service issue reported to branch |

Expected screen: **Review fee adjustment**. Both tests show Fee type = Monthly maintenance and Fee standing = Assessed. Test A shows Fee amount = USD 12.00; Test B shows USD 8.00. The reason, requested resolution, and note match the chosen test. The fee remains unchanged.

What these tests show: The engine reads the correct fee and prepares an explainable request. Full or partial waiver is the requested outcome, not an approval made by AI.

**Negative tests: a safe stop is the correct result**

For each row, start with that feature's full B input column, select its saved capability in Replay mode, and keep Test scenario = Normal workflow unless a different scenario is explicitly stated. Change only the field shown. All other fields retain their B values. If no capability exists yet, complete that feature's discovery first.

| Test | Workflow | Change from B | Expected result | What this shows |
|---|---|---|---|---|
| N1 | Sub-account review | Member ID = 99999 | Outcome; member not found (`member_not_found`); no successful review | The engine stops when the customer does not exist. |
| N2 | Card replacement | Card reference = CARD-10023; keep Member ID = 10042 | Outcome; record not found (`record_not_found`) | A member cannot use another member's card record. |
| N3 | Transaction dispute | Transaction reference = TXN-10042-HOLD | Outcome; request not eligible (`request_not_eligible`); the fixture transaction is pending | The engine respects the target application's eligibility outcome. |
| N4 | Address change | Postal code = INVALID | Outcome; validation error (`validation_error`) | Invalid address data is not reported as success or silently corrected by replay. |
| N5 | Statement request | Account reference = ACC-10042-HOLD | Outcome; request not eligible; document access is restricted | The engine does not bypass document restrictions. |
| N6 | Fee adjustment | Fee reference = FEE-10042-HOLD | Outcome; request not eligible; fee is already adjusted | An ineligible fee request is stopped. |
| N7 | Sub-account review | Member ID = 123 | The browser blocks submission because five digits are required; no new run starts | Invalid input is caught before browser automation. |

Outcome is different from Success. It means the application returned a valid reason the requested work cannot proceed. In discovery, an incomplete or unsuccessful run must not create a new capability. In replay, the existing capability remains available even when this invocation returns an outcome.

The -HOLD suffix deliberately selects an ineligible synthetic record. It is a test convention in this project, not a real banking rule.

**Recovery and failure tests**

Use the complete Sub-account review B inputs for every row: Member ID = 10042, Product = Checking, Account nickname = Travel Fund. Choose Replay capability and a saved sub-account capability. Only change Test scenario as shown.

| Test scenario | Expected behavior | What this shows |
|---|---|---|
| Session expired · human takeover | Run pauses with Needs you. Click Claim session, click Restore session inside the live banking preview, then Return to automation. Expect Success and zero model calls. | A person can resolve an interruption in the same browser, after which replay continues. |
| Known notice · automatic recovery | Activity shows Automatic recovery; the known notice is dismissed and replay reaches Success with zero model calls. | A known interruption can be handled without asking a model again. |
| Permission denied | Run stops with permission denied; no successful review. | The engine does not invent access or bypass the application's restriction. |
| Form validation error | Outcome; validation error; no successful review. | A form rejection is distinguished from successful completion. |

**What to inspect after each test**

- Run status: Success for normal cases; Outcome or Stopped for the relevant negative cases; Needs you during takeover.
- Browser preview: the expected review or interruption is visible in the engine's own banking session.
- Result: the requested values match; on success review ready is true. Extra fields such as transaction amount come from the displayed banking record.
- Model calls: greater than zero for genuine discovery; exactly zero for replay, including the supported human-takeover replay.
- Capability: after successful unassisted discovery, the saved steps use input references so B does not repeat A's member or reference.
- Activity: actions, checkpoints, provider failures, and control transfers explain how the result was reached.

The Open manual sandbox link opens an independent browser session. Actions there are not recorded into the engine's discovery, and they do not resolve an interruption in the engine's preview. For takeover, use the dashboard's live preview.

**Verification already recorded**

Genuine Gemini discovery and matching zero-model replay have been recorded for sub-account review, transaction dispute, and card replacement. Address change, statement request, and fee adjustment have real-browser tests with scripted test planners; successful live Gemini discovery is not yet claimed for those three. The latest full suite passed 141 tests. See evidence/README.md for the exact scope.
