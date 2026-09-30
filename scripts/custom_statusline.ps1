# Custom Statusline Script for Antigravity CLI
# Reads agent state from stdin and outputs formatted status line

$inputData = [Console]::In.ReadToEnd()
if ($inputData) {
    try {
        $state = ConvertFrom-Json $inputData
        
        $modelName = if ($state.model.display_name) {
            $state.model.display_name
        } elseif ($state.model.id) {
            $state.model.id
        } elseif ($state.model -is [string]) {
            $state.model
        } else {
            "$($state.model)"
        }
        
        $model = $modelName -replace '^gemini-', 'g-' -replace '^Gemini ', 'G-'
        $cwd = Split-Path $state.cwd -Leaf
        
        # Extract token usage and cost metrics
        $tokens = 0
        $cost = 0.0
        
        if ($state.context_window) {
            $inTok = [double]($state.context_window.total_input_tokens)
            $outTok = [double]($state.context_window.total_output_tokens)
            $tokens = $inTok + $outTok
            
            # Calcul du coût estimé (API rates / Vertex pricing pour estimation)
            if ($modelName -match "flash" -or $modelName -match "lite" -or $modelName -match "mini") {
                $cost = ($inTok * 0.075 / 1e6) + ($outTok * 0.30 / 1e6)
            } elseif ($modelName -match "claude.*3.*5|sonnet|opus") {
                $cost = ($inTok * 3.0 / 1e6) + ($outTok * 15.0 / 1e6)
            } else {
                # Gemini Pro / 3.1 Pro ($1.25/1M in, $5.00/1M out)
                $cost = ($inTok * 1.25 / 1e6) + ($outTok * 5.00 / 1e6)
            }
        }
        
        if ($state.usage -and $state.usage.totalTokens -gt 0) {
            $tokens = $state.usage.totalTokens
            if ($state.usage.totalCost -gt 0) { $cost = $state.usage.totalCost }
        } elseif ($state.totalTokens -and $tokens -eq 0) {
            $tokens = $state.totalTokens
            if ($state.totalCost -gt 0) { $cost = $state.totalCost }
        } elseif ($state.totalCost -and $state.totalCost -gt 0) {
            $cost = $state.totalCost
        }
        
        # Format tokens to k-notation or M-notation if large
        $tokenStr = $tokens
        if ($tokens -ge 1000000) {
            $tokenStr = "{0:N2}M" -f ($tokens / 1000000)
        } elseif ($tokens -ge 1000) {
            $tokenStr = "{0:N1}k" -f ($tokens / 1000)
        }
        
        # Format cost
        $costStr = if ($cost -ge 10) { "{0:N2}" -f $cost } else { "{0:N4}" -f $cost }
        
        # Output formatted string
        Write-Output "[$model | $cwd | Tok: $tokenStr | Cost: `$$($costStr)]"
    } catch {
        # Fallback in case of parsing error
        Write-Output "[Antigravity | State Parse Err]"
    }
} else {
    Write-Output "[Antigravity | Idle]"
}
