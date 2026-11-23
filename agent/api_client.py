"""Small httpx client for the Tuition API.

Every call goes to GATEWAY_BASE_URL (Azure API Management in the cloud, or the local
api while testing). When a subscription key is set it is sent as Ocp-Apim-Subscription-Key.
"""

import httpx


class ApiError(Exception):
    """Error response from the api, in the api's own format: {code, message, details}."""

    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> dict:
        return {"status": self.status, "code": self.code, "message": self.message, "details": self.details}


class TuitionApiClient:
    def __init__(self, base_url: str, subscription_key: str = "", timeout: float = 15.0,
                 http_client: httpx.Client | None = None):
        headers = {"Accept": "application/json"}
        if subscription_key:
            headers["Ocp-Apim-Subscription-Key"] = subscription_key
        self._http = http_client or httpx.Client(timeout=timeout)
        self._base_url = base_url.rstrip("/")
        self._headers = headers
        self._token: str | None = None

    def close(self):
        self._http.close()

    # ---------- auth ----------

    def login(self, username: str, password: str) -> dict:
        data = self._request("POST", "/auth/token", data={"username": username, "password": password},
                             with_token=False)
        self._token = data["access_token"]
        return data

    def me(self) -> dict:
        return self._request("GET", "/auth/me")

    # ---------- banking ----------

    def query_tuition(self, student_no: str, term: str | None = None) -> dict:
        params = {"term": term} if term else None
        return self._request("GET", f"/banking/tuitions/{student_no}", params=params)

    def pay_tuition(self, student_no: str, term: str, amount: str, transaction_id: str) -> dict:
        body = {"studentNo": student_no, "term": term, "amount": amount, "transactionId": transaction_id}
        return self._request("POST", "/banking/payments", json=body)

    # ---------- helpers ----------

    def _request(self, method: str, path: str, with_token: bool = True, **kwargs) -> dict:
        headers = dict(self._headers)
        if with_token and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = self._http.request(method, self._base_url + path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(0, "GATEWAY_UNREACHABLE", f"could not reach {self._base_url}: {exc}") from exc

        if response.is_success:
            return response.json()
        raise _error_from_response(response)


def _error_from_response(response: httpx.Response) -> ApiError:
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and "code" in body:
        return ApiError(response.status_code, body["code"], body.get("message", ""), body.get("details"))
    # the gateway can answer by itself (wrong subscription key, rate limit ...) with another body
    if isinstance(body, dict) and "message" in body:
        message = body["message"]
    else:
        message = response.text[:200] or response.reason_phrase
    return ApiError(response.status_code, f"HTTP_{response.status_code}", message)
