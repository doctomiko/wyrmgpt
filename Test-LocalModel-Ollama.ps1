ollama list

Invoke-RestMethod http://localhost:11434/v1/models

$headers = @{ Authorization = "Bearer ollama" }
# This is the example test model we loaded which was 
# Meta Llama 3.1 8B Instruct GGUF (Q4_K_M quantized)
# Said to be reasonable, even on a 4060Ti
# We found llama3.1:8b to be MUCH slower than the one we commented out, franky.
# Run this test after running:
#  Quit Ollama from the taskbar menu
#  irm https://ollama.com/install.ps1 | iex
#  ollama pull llama3.1:8b-instruct-q4_K_M
#  ollama run llama3.1:8b-instruct-q4_K_M
$body = @{
  model = "llama3.1:8b-instruct-q4_K_M"
  #model = "llama3.1:8b"
  input = "Reply with exactly: Ollama is alive."
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri http://localhost:11434/v1/responses `
  -Method Post `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body