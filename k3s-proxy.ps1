# k3s-proxy.ps1 — rode como Admin após cada reinicialização

# Remove regra antiga
netsh interface portproxy delete v4tov4 listenport=6443 listenaddress=0.0.0.0

# Pega o IP atual do WSL2 automaticamente
$wslIP = (wsl hostname -I).Trim().Split(" ")[0]

# Recria o redirecionamento com o novo IP
netsh interface portproxy add v4tov4 `
  listenport=6443 `
  listenaddress=0.0.0.0 `
  connectport=6443 `
  connectaddress=$wslIP

Write-Host "Port forwarding configurado para WSL2 IP: $wslIP"