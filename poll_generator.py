import json
from random import choice

from openai import AsyncOpenAI

from group import Group


class PollGenerator:
    _prompt = ('Devi generare un sondaggio per un gruppo di Telegram. '
               'Gli utenti possono scegliere una delle opzioni e scommettere gettoni virtuali. '
               'Questo è l\'argomento suggerito per il sondaggio: {suggestion}. '
               'Utilizza il suggerimento per formulare un sondaggio creativo. Aggiungi del pepe al suggerimento. '
               'Il sondaggio suggerito dovrebbe essere l\'unico testo che generi. '
               'Il sondaggio deve essere espresso in json, nel formato seguente: {'
               '"text": "testo del sondaggio", "options": [{"rating": "(numero) in base al rischio del sondaggio", '
               '"text": "Testo dell\'opzione"}]'
               '}')

    def __init__(self, group: Group):
        self.group = group

    async def generate(self, open_ai: AsyncOpenAI, suggestion: str | None = None, test: bool = False) -> dict:
        if suggestion is None:
            suggestion = choice(self.group.get_suggestions())

        if test:
            return {
                'text': suggestion,
                'options': [
                    {'rating': 1.2, 'text': 'option 1'},
                    {'rating': 1.5, 'text': 'option 2'},
                ]
            }

        return await self._generate_from_prompt(open_ai, suggestion)

    async def _generate_from_prompt(self, open_ai: AsyncOpenAI, suggestion: str) -> dict:
        prompt = self._prompt.replace('{suggestion}', suggestion)

        response = await open_ai.chat.completions.create(
            messages=[{
                'role': 'system',
                'content': prompt,
            }],
            model="gpt-3.5-turbo-0125",
        )

        return (json.decoder
                .JSONDecoder()
                .decode(response.choices[0].message.content))
