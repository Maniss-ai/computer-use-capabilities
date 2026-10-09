"""Synthetic servicing data and forms owned only by the target application.

The automation package must not import these records or use these business functions.
All service actions stage a review; no record, card, fee, or address is changed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceField:
    name: str
    label: str
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Service:
    slug: str
    title: str
    department: str
    description: str
    detail_screen: str
    prepare_screen: str
    review_screen: str
    prepare_button: str
    fields: tuple[ServiceField, ...]
    lookup_name: str = ""
    lookup_label: str = ""
    reference_prefix: str = ""


SERVICES = {
    item.slug: item
    for item in (
        Service(
            "card-replacement",
            "Card services",
            "CARDS",
            "Find the member's card and prepare replacement instructions for staff review.",
            "Card details",
            "Replacement preferences",
            "Review card replacement",
            "Prepare replacement",
            (
                ServiceField(
                    "replacement_reason", "Replacement reason", ("Damaged", "Lost", "Stolen")
                ),
                ServiceField(
                    "replacement_delivery",
                    "Replacement delivery",
                    ("Branch pickup", "Registered address"),
                ),
            ),
            "card_reference",
            "Card reference",
            "CARD",
        ),
        Service(
            "transaction-dispute",
            "Transaction disputes",
            "PAYMENTS",
            "Locate a posted transaction and prepare a dispute intake for investigation.",
            "Transaction details",
            "Dispute details",
            "Review transaction dispute",
            "Prepare dispute",
            (
                ServiceField(
                    "dispute_reason",
                    "Dispute reason",
                    ("Duplicate charge", "Service not received", "Unrecognized transaction"),
                ),
                ServiceField("contact_channel", "Contact channel", ("Secure message", "Phone")),
            ),
            "transaction_reference",
            "Transaction reference",
            "TXN",
        ),
        Service(
            "address-change",
            "Contact maintenance",
            "MEMBER PROFILE",
            "Review the current contact record and stage a mailing-address change for verification.",
            "Contact details",
            "New mailing address",
            "Review address change",
            "Prepare address change",
            (
                ServiceField("street", "Street address"),
                ServiceField("city", "City"),
                ServiceField("region", "State code"),
                ServiceField("postal_code", "Postal code"),
                ServiceField(
                    "verification_method",
                    "Verification method",
                    ("Branch verification", "Callback verification"),
                ),
            ),
        ),
        Service(
            "statement-request",
            "Statements and documents",
            "DOCUMENTS",
            "Select an eligible account and stage a historical statement delivery request.",
            "Statement account",
            "Statement preferences",
            "Review statement request",
            "Prepare statement request",
            (
                ServiceField(
                    "statement_period", "Statement period", ("September 2026", "August 2026")
                ),
                ServiceField("document_format", "Document format", ("PDF", "Paper copy")),
                ServiceField(
                    "document_delivery", "Document delivery", ("Secure inbox", "Branch collection")
                ),
            ),
            "account_reference",
            "Account reference",
            "ACC",
        ),
        Service(
            "fee-adjustment",
            "Fee servicing",
            "SERVICE REQUESTS",
            "Find an assessed fee and assemble an adjustment request for a staff decision.",
            "Fee details",
            "Adjustment details",
            "Review fee adjustment",
            "Prepare adjustment request",
            (
                ServiceField(
                    "adjustment_reason",
                    "Adjustment reason",
                    ("First occurrence", "Service issue", "Incorrect assessment"),
                ),
                ServiceField(
                    "requested_resolution",
                    "Requested resolution",
                    ("Full waiver", "Partial waiver"),
                ),
                ServiceField("supporting_note", "Supporting note"),
            ),
            "fee_reference",
            "Fee reference",
            "FEE",
        ),
    )
}


def record_for(service: Service, member: str, reference: str) -> dict[str, str] | None:
    """Record lookup is member-scoped; another member's reference never matches."""
    if not service.lookup_name:
        return {
            "Current mailing address": f"{int(member[-2:]) + 100} Harbor Avenue",
            "Current city": "San Francisco",
            "Contact standing": "Verified",
        }
    expected = f"{service.reference_prefix}-{member}"
    if reference not in {expected, expected + "-HOLD"}:
        return None
    blocked = reference.endswith("-HOLD")
    if service.slug == "card-replacement":
        return {
            "Card reference": reference,
            "Card product": "Everyday debit",
            "Card standing": "Replacement already pending" if blocked else "Active",
        }
    if service.slug == "transaction-dispute":
        return {
            "Transaction reference": reference,
            "Merchant": "Harbor Market",
            "Transaction amount": "USD 84.20" if member == "10023" else "USD 126.50",
            "Transaction status": "Pending" if blocked else "Posted",
        }
    if service.slug == "statement-request":
        return {
            "Account reference": reference,
            "Account product": "Everyday checking",
            "Document access": "Restricted" if blocked else "Available",
        }
    return {
        "Fee reference": reference,
        "Fee type": "Monthly maintenance",
        "Fee amount": "USD 12.00" if member == "10023" else "USD 8.00",
        "Fee standing": "Already adjusted" if blocked else "Assessed",
    }
