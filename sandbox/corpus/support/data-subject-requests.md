---
title: "Forwarding data subject requests"
---

> [!IMPORTANT]
> Support never answers these requests itself. It recognises them, forwards them to `privacy@quillmoor.example` the same business day, and tells the requester that it has done so.

**Owner:** Femi Haldane, agreed with Beatrix Sallow, the DPO. **Last reviewed:** 2026-06-04.

## What counts

A data subject request is any request from a person about their own personal data. The commonest is a DSAR, in which someone asks what personal data we hold about them and for a copy of it. Others ask us to correct their data, to stop using it for something, or to apply an erasure request. People rarely use the legal terms, so look at what they ask for, not at the words they use. Requests like these all count:

- "What information do you have about me?"
- "Please send me everything you store on my card payments."
- "I want my details removed from your systems."
- "Why did you process my payment, and who did you share it with?"
- "My name is spelt wrong in your records."

They can come from anyone: a merchant's own staff, a seller on a marketplace, or a cardholder who found our name on a statement. A request does not need to be in writing to be valid, so a request made in a chat or in a phone call counts too; write it down on a ticket.

## What to do

1. Open or keep a Harbour ticket for the request. One ticket per requester.
2. Use **Forward to privacy** from the ticket's action menu. It sends the whole ticket to `privacy@quillmoor.example`, adds the tag `dsar` and puts the ticket on hold. Do this the same business day the request arrives, however it arrived.
3. Reply to the requester with the `dsar-forwarded` macro.
4. Leave the ticket on hold. The privacy team replies from its own address and solves the ticket when the request is closed.

Do not ask the requester for identity documents, do not say whether we hold any data about them, and do not send any personal data in your reply, not even to confirm an email address. The privacy team verifies identity and decides what to disclose.

The deadlines that apply to these requests, our role towards merchants and cardholders, and how the answer is put together are set out in the [DPA playbook](../legal/dpa-playbook.md). How an erasure request is applied in the warehouse, and what is kept because the law requires it, is on [Erasure requests in the warehouse](../data/erasure-requests.md). Neither is for support to explain to the requester.

## Special cases

**A merchant asks for help with a request from one of their own customers.** The merchant usually decides how to answer their customer, but often needs data that we hold on their behalf. Forward the ticket to privacy in the same way: the privacy team knows what each merchant's contract allows.

**A cardholder asks us to stop a merchant from charging them.** That is not a data request. Point them to the merchant, or to their issuer, with the `refund-cardholder-redirect` macro; see [Handling merchant refund requests](refunds.md).

**The request is mixed with a complaint or a dispute.** Forward the data part to privacy and handle the rest as usual. Say in the internal note which part you forwarded.

**Someone asks on behalf of another person**, such as a solicitor or a family member. Forward it; do not ask for proof of authority yourself.

**A colleague asks for their own data.** That is not a merchant ticket. Point them to `people@quillmoor.example`.

## Template

`dsar-forwarded`:

> Thank you for your request. I have passed it to our privacy team, who handle all requests about personal data and will reply to you directly from privacy@quillmoor.example. They may need to confirm your identity before they can help. You do not need to send anything else to this address.
