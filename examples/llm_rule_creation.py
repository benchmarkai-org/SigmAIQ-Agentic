# %% This example will demonstrate how to create a Sigma langchain agent chatbot, which can perform various tasks like
# %% automatically translate a rule for you, and create new rules from a users input.
import asyncio

from langchain_openai import OpenAIEmbeddings

from sigmaiq.llm.base import SigmaLLM

import weave
import wandb

# %% Import required SigmAIQ classes and functions
from sigmaiq.llm.toolkits.base import create_sigma_agent

# Initialize wandb run
weave.init("sigmaiq-agentic")

# %% Ensure we have our Sigma vector store setup with our base LLM class
sigma_llm = SigmaLLM(embedding_model=OpenAIEmbeddings(model="text-embedding-3-large"))

try:
    sigma_llm.load_sigma_vectordb()
except Exception as e:
    print(e)
    print("Creating new Sigma VectorDB")
    sigma_llm.create_sigma_vectordb(save=True)

# %% Create a Sigma Agent Executor, and pass it our Sigma VectorDB
sigma_agent_executor = create_sigma_agent(sigma_vectorstore=sigma_llm.sigmadb)

@weave.op() # 🐝
async def main():

    # %% RULE SEARCHING
    print("\n--------\nRULE SEARCHING\n--------\n")
    user_input = (
        "Search for a Sigma process rule that detects the use of vim and it's siblings commands to execute a shell or proxy commands.\n"
        "Such behavior may be associated with privilege escalation, unauthorized command execution, or to break out from restricted environments."
    )
 
    answer = await sigma_agent_executor.ainvoke({"input": user_input})
    print(f"QUESTION:\n {user_input}", end="\n\n")
    print("ANSWER: \n")
    print(answer.get("output"), end="\n\n")

 
    # %% RULE CREATION
    # %% The agent will take the user input, look up similar Sigma Rules in the Sigma vector store, then create a brand
    # %% new rule based on the context of the users input and the similar Sigma Rules.
    print("\n--------\nRULE CREATION\n--------\n")

    user_input = (
        "Create a Sigma process rule that detects the use of vim and it's siblings commands to execute a shell or proxy commands.\n"
        "Such behavior may be associated with privilege escalation, unauthorized command execution, or to break out from restricted environments."
    )

    answer = await sigma_agent_executor.ainvoke({"input": user_input})
    print(f"QUESTION:\n {user_input}", end="\n\n")
    print("ANSWER: \n")
    print(answer.get("output"), end="\n\n")


if __name__ == "__main__":
    asyncio.run(main())
