---
title: "Testing strategy"
---

# Testing strategy

Owner: the backend guild, with the frontend guild for Merchant Hub. Last reviewed: 2026-07-29.

We test so that we can change code safely, not to reach a number. This page says which kinds of test we write, where each runs, and what we do about tests that lie.

## The layers

| Layer | What it checks | Where it runs | Time budget |
|---|---|---|---|
| Unit | One function or type, with no I/O | Laptop and every CI run | Whole suite under 2 minutes |
| Integration | One service against real PostgreSQL and Apache Kafka | Laptop under `qm`, and CI | Under 8 minutes |
| Contract | The events and APIs between services | CI, on both sides of each contract | Under 3 minutes |
| End-to-end | A merchant's journey across services | `staging-eu`, after each deploy to staging | Under 20 minutes |

Most tests should be unit tests, a fair number integration tests, and only a few end-to-end tests, covering the journeys that would cost us most if they broke: take a card payment, refund it, pay out a seller, and see all three in Merchant Hub.

## Unit tests

Test behaviour through the public interface. If a refactor that keeps behaviour breaks a test, the test was checking the implementation. Expectations come from the requirement (the pricing rule, the ADR, the scheme's documented behaviour), never from running the code and pasting its output into an assertion.

Table-driven tests are the norm in Go:

```go
func TestPlatformFee(t *testing.T) {
	cases := []struct {
		name      string
		amount    int64
		rateBps   int64
		wantMinor int64
	}{
		{"zero amount", 0, 290, 0},
		{"half a penny rounds up", 250, 500, 13},
		{"one million pounds", 100_000_000, 290, 2_900_000},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := PlatformFee(tc.amount, tc.rateBps); got != tc.wantMinor {
				t.Errorf("PlatformFee(%d, %d) = %d, want %d", tc.amount, tc.rateBps, got, tc.wantMinor)
			}
		})
	}
}
```

## Integration tests

Integration tests run against the same PostgreSQL and Kafka versions as production, started by `qm` on a laptop (see [local development environment](local-development.md)) and by CI in the same containers. Each test creates its own schema or topic and cleans up after itself, so tests never depend on their order.

```python
import pytest

from payout_gateway.batches import BatchRepository


@pytest.mark.integration
def test_lost_acknowledgement_does_not_pay_twice(db, stub_bank):
    repo = BatchRepository(db)
    batch = repo.create(payout_ids=["payout-1", "payout-2"])

    stub_bank.drop_next_ack()
    repo.submit(batch.id)
    repo.submit(batch.id)  # the scheduler's retry after the lost acknowledgement

    assert stub_bank.paid_payout_ids() == ["payout-1", "payout-2"]
```

## Contract tests

Services talk through events on the replicated log ([ADR-019](../architecture/adr-019-replicated-event-log.md)) and through HTTP APIs. A consumer writes down what it relies on; the producer's CI checks every change against all its consumers' contracts and fails the change before it can break them. Contracts live in the producer's repository under `contracts/`, one directory per consumer, owned by the consuming team through the owners file.

## End-to-end tests

End-to-end tests run in the [staging environments](../release/staging-environments.md) against the [test merchants and test cards](../payments/test-merchants.md). They are slow and the most likely to flake, so we keep them few: if a contract test can cover a journey, it should.

## Flaky tests

A test that sometimes fails without any change to the code is flaky, and it is worse than no test, because it teaches everyone to press "retry".

1. Whoever first sees the flake quarantines the test with the `quarantine` marker, in a change of its own.
2. The owning team opens a ticket labelled `flaky-test` within one business day.
3. The test is fixed or deleted within 10 business days. Quarantined tests still run but cannot fail the build, and the Lantern dashboard "CI health" lists them by age.

## Coverage

We set no coverage target for whole repositories. CI reports the coverage of changed lines, and reviewers ask about new code that no test reaches. On payments services, a change whose failure paths are untested does not get its second approval.
