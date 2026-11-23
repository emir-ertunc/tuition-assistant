# API Gateway (Azure API Management)

All REST calls of the project (mobile app, banking app, admin site and the AI Agent) go
through Azure API Management. The MCP server is **not** behind the gateway, the agent calls
it directly.

- Tier: **Consumption** (pay per call, the first 1 million calls per month are free)
- Created by [`deploy/azure-gateway.ps1`](../deploy/azure-gateway.ps1)
- Policy: [`api-policy.xml`](api-policy.xml)
- Gateway URL: **`https://tuition-apim-ee7141.azure-api.net/api/v1`**
- Backend: `https://tuition-api-ee7141.azurewebsites.net` (refuses `/api` calls that do not come
  through the gateway)

## Versioning

The api is published on the path `api/v1`. The backend routes are also under `/api/v1`, so
a future breaking version would be a new `v2` router in the code and a new `api/v2` api in
APIM, while `v1` keeps working.

## Route mappings

| Public route (gateway) | Backend (App Service) | Gateway check |
|---|---|---|
| `POST /api/v1/auth/token` | `POST /api/v1/auth/token` | none (login) |
| `GET /api/v1/auth/me` | `GET /api/v1/auth/me` | valid JWT |
| `GET /api/v1/mobile/tuitions/{studentNo}` | same | none, 3 per student per day (counted by the api, 429 passed through) |
| `GET /api/v1/banking/tuitions/{studentNo}` | same | valid JWT + role BANK or STUDENT |
| `POST /api/v1/banking/payments` | same | valid JWT + role BANK or STUDENT |
| `POST /api/v1/admin/tuitions` | same | valid JWT + role ADMIN |
| `POST /api/v1/admin/tuitions/batch` | same | valid JWT + role ADMIN |
| `GET /api/v1/admin/tuitions/unpaid` | same | valid JWT + role ADMIN |

The operations are imported from the api's `openapi.json` (`deploy/prepare_openapi.py`
removes the `/api/v1` prefix because APIM adds the api path itself).

## What the policy does

1. **JWT check** (`validate-jwt`, HS256, issuer `tuition-api`, audience `tuition-clients`).
   No / bad / expired token → `401`. Valid token with the wrong role → `403`.
   The signing key is the base64 of the api's `JWT_SECRET`, kept as the secret named value
   `jwt-signing-key`.
2. **Gateway key**: the gateway adds `X-Gateway-Key` to every request. On Azure the api has
   `GATEWAY_KEY` set and answers `403 "requests must go through the API gateway"` to `/api`
   calls that do not have it, so the gateway can not be skipped. The header is removed from
   the response.
3. **Same error format** as the api: gateway errors are returned as
   `{"code": "...", "message": "...", "details": [...]}`.
4. **CORS** for the swagger page of the api (its "Try it out" sends the requests to the gateway).
5. Every response gets `X-Api-Gateway: tuition-apim`, so it is easy to see that a response came
   through the gateway.

The api itself also checks the token, the role and the student number, so the rules are the
same on both layers.

### Daily limit (3 mobile queries per student)

The limit is keyed by the **student number**, not the client ip. The Consumption tier does not
have the `quota-by-key` / `rate-limit-by-key` policies, so the counter lives in the api
(`tuition_query_logs` table, one row per student per day). The 4th call returns
`429 QUERY_LIMIT_EXCEEDED` with a `Retry-After` header and the gateway passes it to the client.
With the Developer or Standard tier the same rule could also be added on the gateway with
`quota-by-key` and `counter-key="@(context.Request.MatchedParameters["studentNo"])"`.

## Checked on the deployed gateway

| Request | Result |
|---|---|
| `GET https://tuition-api-ee7141.azurewebsites.net/api/v1/mobile/tuitions/20210002` (direct, no gateway) | `403 FORBIDDEN "requests must go through the API gateway"` |
| `POST /api/v1/auth/token` (student) | `200` + token |
| `GET /api/v1/banking/tuitions/20210001` without token | `401 UNAUTHORIZED` (gateway) |
| same with a broken token | `401 UNAUTHORIZED` (gateway) |
| `GET /api/v1/admin/tuitions/unpaid` with a student token | `403 FORBIDDEN` (gateway, role claim) |
| `GET /api/v1/banking/tuitions/20210001` with the student's own token (**protected route**) | `200` |
| `GET /api/v1/banking/tuitions/20210003` with student 20210001's token | `403 FORBIDDEN` (api, other student) |
| `GET /api/v1/admin/tuitions/unpaid?term=2026-FALL` with admin token | `200` paged list |
| `GET /api/v1/mobile/tuitions/20210002` 4 times | `200, 200, 200, 429` + `Retry-After` |

Every response had the header `X-Api-Gateway: tuition-apim`.

## Example error response (through the gateway)

```
GET https://tuition-apim-ee7141.azure-api.net/api/v1/banking/tuitions/20210001   (no Authorization header)

HTTP/1.1 401 Unauthorized
X-Api-Gateway: tuition-apim

{
  "code": "UNAUTHORIZED",
  "message": "JWT not present.",
  "details": ["gateway: TokenNotPresent"]
}
```

```
GET https://tuition-apim-ee7141.azure-api.net/api/v1/admin/tuitions/unpaid?term=2026-FALL   (student token)

HTTP/1.1 403 Forbidden
X-Api-Gateway: tuition-apim

{
  "code": "FORBIDDEN",
  "message": "Claim value mismatch: role=ADMIN.",
  "details": ["gateway: TokenClaimValueMismatch"]
}
```

A route that does not exist on the gateway (e.g. `/api/v1/nothing`) gets the default APIM
404 (`{"statusCode": 404, "message": "Resource not found"}`), it never reaches the api.
