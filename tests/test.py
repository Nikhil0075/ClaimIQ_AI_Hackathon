import os
from openai import OpenAI
from dotenv import load_dotenv

# Load your API key from a secure local .env file
load_dotenv()

# Initialize the authenticated client
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

try:
    # Initiate a chat completion request
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant."
            },
            {
                "role": "user",
                "content": "Write a short poem about clean Python code."
            }
        ],
        model="gpt-4o", # Replace with your target model
    )

    # Extract and print the returned text
    print(chat_completion.choices[0].message.content)

except Exception as e:
    print(f"An error occurred: {e}")
