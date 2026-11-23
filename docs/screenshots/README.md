# Screenshots

| File | What it shows |
|---|---|
| [agent-scenarios.png](agent-scenarios.png) | chat as student 20210001 through the Azure gateway + MCP server: MCP only ("When is the payment deadline?"), API only ("What is my balance?"), combined ("Can I pay my outstanding balance in installments?") and the payment with the confirmation box (`yes` → SUCCESS, remaining 2500.00) |
| [gateway-protected-route.png](gateway-protected-route.png) | `deploy/check-gateway.ps1`: protected banking route through the gateway with a token → 200 (`X-Api-Gateway: tuition-apim`); the 401 without a token is in [gateway/README.md](../../gateway/README.md#example-error-response-through-the-gateway) |
| [swagger-1.png](swagger-1.png) | Swagger UI of the deployed Tuition API (versioned `/api/v1` routes per client) |
| [swagger-2.png](swagger-2.png) | Swagger UI: health route and the DTO schemas |
| [unit-tests.png](unit-tests.png) | `pytest` of the three services |
