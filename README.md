# hospital-delirium-alert

## install dependencies
`pip install -r requirements.txt`

## create a .env file with your credentials
edit .env with your MongoDB URI
cp .env.example .env

# run (root directory)
`python -m uvicorn backend.main:app --reload`
