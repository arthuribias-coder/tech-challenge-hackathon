"""
Ferramentas do agente ReAct de chat STRIDE.

Todas as tools são baseadas em conhecimento embutido (sem chamadas externas),
garantindo baixa latência e sem dependências de APIs adicionais.
São registradas via @tool do LangChain e injetadas no create_react_agent.
"""

from __future__ import annotations

from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# Base de conhecimento embutida
# ---------------------------------------------------------------------------

_STRIDE_DETAILS: dict[str, dict] = {
    "spoofing": {
        "name": "Spoofing (Falsificação de Identidade)",
        "description": (
            "O atacante se passa por outro usuário, processo ou sistema. "
            "Exemplos: roubo de credenciais, falsificação de certificados TLS, "
            "IP spoofing, session hijacking e request forgery (CSRF)."
        ),
        "controls": [
            "Autenticação forte (MFA/FIDO2)",
            "Certificados TLS válidos e mutual TLS (mTLS) para serviços internos",
            "Validação e binding de sessão (IP, user-agent)",
            "CSRF tokens em formulários e APIs stateful",
            "Assinatura digital de mensagens (JWT com RS256/ES256)",
        ],
        "mitre": ["T1078 (Valid Accounts)", "T1550 (Use Alternate Auth Material)", "T1134 (Access Token Manipulation)"],
    },
    "tampering": {
        "name": "Tampering (Adulteração)",
        "description": (
            "Modificação não autorizada de dados em trânsito ou em repouso. "
            "Exemplos: SQL injection, man-in-the-middle, alteração de cookies/JWTs, "
            "modificação de arquivos de configuração."
        ),
        "controls": [
            "Criptografia TLS 1.3 em trânsito",
            "Assinatura de mensagens (HMAC, JWT assinado)",
            "Integridade de dados em repouso (checksums, AEAD)",
            "Validação rigorosa de entrada (allowlist, não blocklist)",
            "Controles de integridade de arquivo (hash verificado no deploy)",
        ],
        "mitre": ["T1565 (Data Manipulation)", "T1190 (Exploit Public-Facing Application)", "T1059 (Command and Scripting Interpreter)"],
    },
    "repudiation": {
        "name": "Repudiation (Repúdio)",
        "description": (
            "Um usuário nega ter realizado uma ação por ausência de evidências. "
            "Exemplos: transações negadas sem log, deleção de registros de auditoria, "
            "ações realizadas por conta comprometida sem rastro."
        ),
        "controls": [
            "Logs de auditoria imutáveis (append-only, WORM storage)",
            "Assinatura digital de transações críticas",
            "Timestamps seguros sincronizados (NTP com autenticação)",
            "Correlação de eventos com SIEM (Splunk, ELK)",
            "Non-repudiation via PKI para operações críticas",
        ],
        "mitre": ["T1070 (Indicator Removal)", "T1562 (Impair Defenses)"],
    },
    "information disclosure": {
        "name": "Information Disclosure (Vazamento de Informações)",
        "description": (
            "Exposição indevida de dados sensíveis. "
            "Exemplos: mensagens de erro detalhadas, directory listing, "
            "dados em logs, respostas de API excessivamente verbosas, "
            "side-channel attacks."
        ),
        "controls": [
            "Mensagens de erro genéricas para o usuário (detalhes apenas em logs internos)",
            "Desabilitar directory listing e debug endpoints em produção",
            "Data masking em logs (PII, senhas, tokens)",
            "Princípio do mínimo privilégio em ACLs de dados",
            "Classificação e criptografia de dados sensíveis em repouso",
        ],
        "mitre": ["T1552 (Unsecured Credentials)", "T1213 (Data from Information Repositories)", "T1530 (Data from Cloud Storage)"],
    },
    "denial of service": {
        "name": "Denial of Service (Negação de Serviço)",
        "description": (
            "Tornar um serviço indisponível para usuários legítimos. "
            "Exemplos: DDoS volumétrico, resource exhaustion (CPU/memória), "
            "slow HTTP attacks, XML bomb, ReDoS."
        ),
        "controls": [
            "Rate limiting e throttling por IP/usuário/API key",
            "WAF com regras anti-DDoS (AWS Shield, Cloudflare)",
            "Circuit breakers (Resilience4j, Hystrix) para dependências externas",
            "Limites de tamanho de payload e timeout em todas as requisições",
            "Auto-scaling e capacity planning baseado em métricas",
        ],
        "mitre": ["T1499 (Endpoint Denial of Service)", "T1498 (Network Denial of Service)"],
    },
    "elevation of privilege": {
        "name": "Elevation of Privilege (Escalada de Privilégios)",
        "description": (
            "Obtenção de acesso não autorizado a recursos ou operações privilegiadas. "
            "Exemplos: privilege escalation via vulnerabilidade, IDOR, "
            "misconfigured IAM roles, container escape."
        ),
        "controls": [
            "Princípio do mínimo privilégio (Least Privilege) em todas as identidades",
            "RBAC/ABAC granular com revisão periódica de permissões",
            "Controles de autorização no servidor (nunca confiar no cliente)",
            "Containers sem root (non-root UID, read-only filesystem)",
            "Análise estática de configurações IAM (IAM Access Analyzer)",
        ],
        "mitre": ["T1068 (Exploitation for Privilege Escalation)", "T1548 (Abuse Elevation Control Mechanism)", "T1611 (Escape to Host)"],
    },
}

_RISK_MATRIX: dict[str, dict[str, int]] = {
    "crítica": {"alta": 10, "média": 9, "baixa": 8},
    "alta":    {"alta": 9, "média": 7, "baixa": 5},
    "média":  {"alta": 7, "média": 5, "baixa": 3},
    "baixa":  {"alta": 5, "média": 3, "baixa": 1},
}

_OWASP_MAPPING: dict[str, list[str]] = {
    "injection":         ["A03:2021 – Injection"],
    "broken auth":       ["A07:2021 – Identification and Authentication Failures"],
    "xss":               ["A03:2021 – Injection", "A05:2021 – Security Misconfiguration"],
    "idor":              ["A01:2021 – Broken Access Control"],
    "security misconfig":["A05:2021 – Security Misconfiguration"],
    "crypto failures":   ["A02:2021 – Cryptographic Failures"],
    "ssrf":              ["A10:2021 – Server-Side Request Forgery"],
    "supply chain":      ["A06:2021 – Vulnerable and Outdated Components"],
    "logging":           ["A09:2021 – Security Logging and Monitoring Failures"],
    "deserialization":   ["A08:2021 – Software and Data Integrity Failures"],
}


# ---------------------------------------------------------------------------
# Tools registradas no agente
# ---------------------------------------------------------------------------


@tool
def explain_stride_category(category: str) -> str:
    """
    Retorna explicação detalhada de uma categoria STRIDE com exemplos práticos,
    controles recomendados e mapeamentos para MITRE ATT&CK.
    Aceita o nome em português ou inglês (ex: 'Spoofing', 'Repúdio', 'DoS').
    """
    normalized = category.lower().strip()

    # Mapeamento de aliases em português
    aliases = {
        "falsificação": "spoofing",
        "adulteração": "tampering",
        "repúdio": "repudiation",
        "repudio": "repudiation",
        "vazamento": "information disclosure",
        "divulgação": "information disclosure",
        "dos": "denial of service",
        "negação": "denial of service",
        "escalada": "elevation of privilege",
        "privilégio": "elevation of privilege",
    }

    key = aliases.get(normalized, normalized)
    data = _STRIDE_DETAILS.get(key)

    if not data:
        available = ", ".join(_STRIDE_DETAILS.keys())
        return f"Categoria não encontrada. Categorias disponíveis: {available}"

    lines = [
        f"## {data['name']}",
        "",
        data["description"],
        "",
        "**Controles recomendados:**",
        *[f"- {c}" for c in data["controls"]],
        "",
        "**MITRE ATT&CK relacionados:**",
        *[f"- {m}" for m in data["mitre"]],
    ]
    return "\n".join(lines)


@tool
def calculate_risk_score(severity: str, likelihood: str) -> str:
    """
    Calcula o score de risco (1-10) e classificação com base na severidade do impacto
    e na probabilidade de ocorrência.
    Parâmetros: severity e likelihood devem ser 'crítica', 'alta', 'média' ou 'baixa'.
    """
    sev = severity.lower().strip()
    lik = likelihood.lower().strip()

    # Normaliza variações em português
    norm = {"critica": "crítica", "crítico": "crítica", "alto": "alta", "medio": "média", "baixo": "baixa"}
    sev = norm.get(sev, sev)
    lik = norm.get(lik, lik)

    row = _RISK_MATRIX.get(sev)
    if not row:
        return f"Severidade inválida: '{severity}'. Use: crítica, alta, média ou baixa."

    score = row.get(lik)
    if score is None:
        return f"Probabilidade inválida: '{likelihood}'. Use: alta, média ou baixa."

    if score >= 9:
        level, action = "CRÍTICO", "Ação imediata e emergencial"
    elif score >= 7:
        level, action = "ALTO", "Ação imediata necessária"
    elif score >= 5:
        level, action = "ALTO", "Mitigação prioritária (próximo sprint)"
    elif score >= 3:
        level, action = "MÉDIO", "Planejamento de mitigação no roadmap"
    else:
        level, action = "BAIXO", "Monitoramento e aceite de risco"

    return (
        f"**Score de Risco: {score}/9 — {level}**\n\n"
        f"- Severidade do impacto: {severity}\n"
        f"- Probabilidade: {likelihood}\n"
        f"- Recomendação: {action}\n\n"
        f"Metodologia: OWASP Risk Rating (Impacto × Probabilidade, escala 1-9)"
    )


@tool
def map_to_mitre_attack(stride_category: str, component_type: str = "") -> str:
    """
    Mapeia uma ameaça STRIDE para táticas e técnicas do framework MITRE ATT&CK.
    stride_category: nome da categoria STRIDE (ex: 'Elevation of Privilege').
    component_type: tipo do componente afetado (ex: 'API', 'banco de dados') — opcional.
    """
    key = stride_category.lower().strip()
    data = _STRIDE_DETAILS.get(key)

    if not data:
        # Tenta match parcial
        for k, v in _STRIDE_DETAILS.items():
            if k in key or key in k:
                data = v
                break

    if not data:
        return f"Não foi possível mapear '{stride_category}' para MITRE ATT&CK. Verifique o nome da categoria."

    lines = [
        f"## MITRE ATT&CK para {data['name']}",
        "",
        "**Técnicas principais:**",
        *[f"- [{m}](https://attack.mitre.org/techniques/{m.split('(')[0].strip().replace('T', 'T').strip()})" for m in data["mitre"]],
    ]

    if component_type:
        lines += [
            "",
            f"**Considerações para componente do tipo '{component_type}':**",
            f"Foque especialmente em técnicas de acesso inicial e movimento lateral "
            f"que exploram características de {component_type}.",
        ]

    lines += [
        "",
        "Referência: https://attack.mitre.org",
    ]

    return "\n".join(lines)


@tool
def get_owasp_controls(threat_keyword: str) -> str:
    """
    Retorna controles e categorias OWASP Top 10 (2021) relevantes para um tipo de ameaça.
    threat_keyword: palavra-chave da ameaça (ex: 'injection', 'autenticação', 'XSS', 'IDOR').
    """
    normalized = threat_keyword.lower().strip()

    matched: list[str] = []
    for keyword, items in _OWASP_MAPPING.items():
        if keyword in normalized or normalized in keyword:
            matched.extend(items)

    if not matched:
        matched = [
            "A01:2021 – Broken Access Control",
            "A05:2021 – Security Misconfiguration",
            "A09:2021 – Security Logging and Monitoring Failures",
        ]
        note = (
            f"\nNota: Não encontrei um mapeamento específico para '{threat_keyword}'. "
            "Exibindo controles genéricos mais comuns."
        )
    else:
        note = ""
        matched = list(dict.fromkeys(matched))  # dedup

    lines = [
        f"## OWASP Top 10 (2021) para '{threat_keyword}'",
        "",
        "**Categorias relacionadas:**",
        *[f"- {item}" for item in matched],
        "",
        f"Referência: https://owasp.org/Top10{note}",
    ]
    return "\n".join(lines)


# Lista de tools para injeção no agente
STRIDE_TOOLS = [
    explain_stride_category,
    calculate_risk_score,
    map_to_mitre_attack,
    get_owasp_controls,
]
