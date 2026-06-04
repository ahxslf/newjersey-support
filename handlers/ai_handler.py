from openai import AsyncOpenAI
from config import GROQ_API_KEY, SYSTEM_PROMPT, SUMMARY_PROMPT, IMPORTANCE_CHECK_PROMPT

client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

class AIHandler:
    def __init__(self):
        self.model = "llama-3.3-70b-versatile"

    async def get_response(self, user_message: str, history: list[dict]) -> str:
        try:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            for msg in history[:-1]:
                messages.append({"role": msg["role"], "content": msg["content"]})
            messages.append({"role": "user", "content": user_message})

            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
            return response.choices[0].message.content

        except Exception as e:
            print(f"[AI Error] {e}")
            return (
                "I'm having trouble processing your request right now. "
                "A staff member will assist you shortly."
            )

    async def generate_summary(self, conversation: list[dict]) -> str:
        try:
            conversation_text = "\n".join([
                f"{msg['role'].upper()}: {msg['content']}"
                for msg in conversation
            ])
            prompt = SUMMARY_PROMPT.format(conversation=conversation_text)

            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content

        except Exception as e:
            print(f"[Summary Error] {e}")
            return "**📋 Summary could not be generated automatically.**"

    async def check_importance(self, conversation: list[dict]) -> bool:
        """
        Konuşmanın önemli olup olmadığını kontrol eder.
        True = IMPORTANT (staff attention gerekli)
        False = UNIMPORTANT (basit soru, AI çözmüş)
        """
        try:
            conversation_text = "\n".join([
                f"{msg['role'].upper()}: {msg['content']}"
                for msg in conversation
            ])
            prompt = IMPORTANCE_CHECK_PROMPT.format(conversation=conversation_text)

            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
            result = response.choices[0].message.content.strip().upper()
            print(f"[Importance Check] Result: {result}")
            return "IMPORTANT" in result

        except Exception as e:
            print(f"[Importance Check Error] {e}")
            # Hata durumunda güvenli tarafta kal — önemli say
            return True
