from google import genai
from google.genai import errors, types

from inquest.investigation.provider import Completion, ProviderUnavailable, RetryableProviderError


class GeminiProvider:
    def __init__(self, key: str, model: str = "gemini-3.1-flash-lite") -> None:
        self.client = genai.Client(api_key=key)
        self.model = model
        self.identity = f"gemini:{model}"

    def complete(self, prompt: str, output_tokens: int, timeout: float) -> Completion:
        try:
            result = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0,
                    max_output_tokens=output_tokens,
                    http_options=types.HttpOptions(
                        timeout=int(timeout * 1000),
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                ),
            )
        except errors.APIError as exc:
            if exc.code == 429 or exc.code >= 500:
                raise RetryableProviderError from exc
            raise ProviderUnavailable("provider_rejected_request") from exc
        if result.usage_metadata is None or result.usage_metadata.total_token_count is None:
            raise ProviderUnavailable("missing_provider_result")
        return Completion(content=result.text or "", tokens=result.usage_metadata.total_token_count)
