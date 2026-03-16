Invoke-RestMethod http://localhost:1234/v1/models

# This is the example test model we loaded which was 
# Meta Llama 3.1 8B Instruct GGUF (Q4_K_M quantized)
# Said to be reasonable, even on a 4060Ti
$body = @{
  model = "meta-llama-3.1-8b-instruct"
  input = "Reply with exactly: LM Studio is alive."
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri http://localhost:1234/v1/responses `
  -Method Post `
  -ContentType "application/json" `
  -Body $body