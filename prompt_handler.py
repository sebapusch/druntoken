import json.decoder

from openai import AsyncOpenAI


class PromptHandler:
    def __init__(self, prompt_path: str):
        self._client = AsyncOpenAI()
        self._json_decoder = json.decoder.JSONDecoder()
        self._load_prompts(prompt_path)

    def _load_prompts(self, path: str):
        try:
            with open(path) as file:
                self._prompts: dict[str, str] = self._json_decoder.decode(file.read())
        except Exception as e:
            raise ValueError(f'Unable to load prompts from location "{path}": {e}')

    async def prompt(self, key: str, values: dict[str, str] | None = None) -> str:
        if key not in self._prompts:
            raise ValueError(f'Unknown prompt key "{key}"')

        prompt = self._prompts[key]
        if values is not None:
            for k in values:
                prompt.replace('{' + k + '}', values[k].strip())

        try:
            response = await self._client.chat.completions.create(
                messages=[{
                    'role': 'system',
                    'content': prompt,
                }],
                model="gpt-3.5-turbo-0125",
            )
        except Exception as e:
            raise PromptError(f'Unable to generate prompt response: {e}')

        return response.choices[0].message.content

    async def json_prompt(self, key: str, values: dict[str, str] | None = None) -> dict:
        return self._json_decoder.decode(await self.prompt(key, values))


class PromptError(Exception):
    pass


