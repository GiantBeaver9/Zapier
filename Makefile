# TriggersAPI -- convenience targets. The demo keys are published on purpose
# (D10) so a reviewer can run everything in one command.

BASE ?= http://localhost:8000
KEY_A ?= demo-key-a
KEY_B ?= demo-key-b

.PHONY: help up down logs test client-a produce-a produce-b inbox-a inbox-b last-a

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

up: ## Start API + seeded Postgres
	docker compose up --build

down: ## Stop and remove containers + volumes
	docker compose down -v

logs: ## Tail the API logs
	docker compose logs -f api

test: ## Run the pytest suite (in-memory, no DB needed)
	pytest

client-a: ## Run the example client end-to-end as cust_a
	python client/example.py --base $(BASE) --key $(KEY_A)

produce-a: ## Produce one event as cust_a
	curl -sX POST $(BASE)/v1/events -H "Authorization: Bearer $(KEY_A)" \
		-H "Content-Type: application/json" \
		-d '{"event_id":"evt-$(shell date +%s)","event_type":"order.created","payload":{"order_id":9931}}' ; echo

produce-b: ## Produce one event as cust_b
	curl -sX POST $(BASE)/v1/events -H "Authorization: Bearer $(KEY_B)" \
		-H "Content-Type: application/json" \
		-d '{"event_id":"evt-$(shell date +%s)","event_type":"order.created","payload":{"order_id":42}}' ; echo

inbox-a: ## Pull cust_a's inbox (marks read)
	curl -s $(BASE)/v1/inbox -H "Authorization: Bearer $(KEY_A)" ; echo

inbox-b: ## Pull cust_b's inbox (marks read)
	curl -s $(BASE)/v1/inbox -H "Authorization: Bearer $(KEY_B)" ; echo

last-a: ## Peek cust_a's most-recent events (does not mark read)
	curl -s "$(BASE)/v1/last?num=50" -H "Authorization: Bearer $(KEY_A)" ; echo
