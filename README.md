# VDR Assistant MVP 2

VDR Assistant MVP 2 is a local Streamlit application for asking questions against documents indexed in an OpenAI vector store.

The current MVP supports one active VDR project at a time and one OpenAI vector store ID at a time.

## Current functionality

- Ask questions about VDR documents
- Retrieve answers using OpenAI File Search
- Display source files for supported answers
- Return a fallback response when information is not found in the VDR documents
- Maintain short conversation history for follow-up questions
- Reset the chat session from the sidebar

## Fallback behavior

If the answer cannot be supported by retrieved VDR documents, the app returns:

```text
I can not find this information in the VDR documents
```

## Local setup

### 1. Clone the repository

```powershell
git clone <repository-url>
cd VDR-Assistant-MVP-2
```

### 2. Create a virtual environment

```powershell
python -m venv .venv
```

### 3. Activate the virtual environment

```powershell
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then activate the environment again.

### 4. Install dependencies

```powershell
pip install -r requirements.txt
```

### 5. Create a local `.env` file

Create a file called `.env` in the project root.

Example:

```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1
VECTOR_STORE_ID=your_vector_store_id_here
```

Do not commit `.env` to GitHub.

### 6. Run the Streamlit app

```powershell
streamlit run app/main.py
```

The app should open in the browser.

## Project structure

```text
VDR-Assistant-MVP-2/
|-- app/
|   |-- main.py
|-- src/
|   |-- chains/
|   |-- config/
|   |-- context/
|   |-- ingestion/
|   |-- prompts/
|   |-- retrieval/
|   |-- schemas/
|   |-- ui/
|   |-- validation/
|-- tests/
|-- .env.example
|-- .gitignore
|-- README.md
|-- requirements.txt
```

## Notes for team members

The OpenAI vector store is the searchable index used by the application. It is not the original VDR folder.

Each team member needs:

- Access to the GitHub repository
- A valid OpenAI API key
- The correct OpenAI vector store ID
- A local `.env` file

## Current scope

Implemented:

- Local Streamlit Q&A workflow
- OpenAI File Search integration
- Source file display
- Basic answer validation
- Basic error handling
- Reset chat button

Not implemented yet:

- VDR ingestion from local folders
- Folder structure preservation
- Compare workflow
- Summarize workflow
- User authentication
- Deployment