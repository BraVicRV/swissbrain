import requests
import hashlib
from typing import Dict, Any, List
from datetime import datetime, timedelta
from modules.base import BaseModule

class SentinelModule(BaseModule):
    def __init__(self):
        super().__init__(
            name="sentinel",
            description="Vigila seguridad digital: breaches, vulnerabilidades, estafas"
        )
        self.monitored_emails = []
        self.monitored_domains = []
        self.known_breaches = set()
        self.last_cve_check = None
        self.max_alerts_per_cycle = 3
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        check_type = params.get("check_type", "full")
        email = params.get("email", "")
        
        findings = []
        
        if check_type in ["full", "breach"] and email:
            breach_result = await self._check_email_breach(email)
            if breach_result:
                findings.append(breach_result)
        
        if check_type in ["full", "vulns"]:
            vulns = await self._check_recent_vulns()
            findings.extend(vulns)
        
        # >>> FIX: Si no hay findings, informar al usuario qué pasó
        if not findings:
            if email:
                msg = f"✅ No se detectaron brechas para {email} ni vulnerabilidades críticas activas que te afecten."
            else:
                msg = ("🔍 *Check de seguridad completado*\n\n"
                       "Para verificar si tu email está comprometido, envíame tu email así:\n"
                       "`Revisa si miemail@ejemplo.com está comprometido`\n\n"
                       "Mientras tanto, no se detectaron vulnerabilidades críticas activas.")
            
            findings.append({
                "title": "Sentinel: Estado de seguridad",
                "content": msg,
                "priority": "baja"
            })
        
        return {
            "findings": findings,
            "status": "completed"
        }
    
    async def autonomous_check(self) -> List[Dict[str, Any]]:
        findings = []
        alert_count = 0
        
        # 1. Breaches (máx 1)
        for email in self.monitored_emails[:1]:
            if alert_count >= self.max_alerts_per_cycle:
                break
            result = await self._check_email_breach(email)
            if result:
                findings.append(result)
                alert_count += 1
        
        # 2. Vulns que afectan al usuario (máx 2)
        if alert_count < self.max_alerts_per_cycle:
            vulns = await self._check_recent_vulns()
            user_vulns = [v for v in vulns if v.get("metadata", {}).get("affects_user", False)]
            for vuln in user_vulns[:2]:
                if alert_count >= self.max_alerts_per_cycle:
                    break
                findings.append(vuln)
                alert_count += 1
        
        # 3. Phishing (máx 1)
        if alert_count < self.max_alerts_per_cycle:
            phishing = await self._check_phishing_domains()
            for p in phishing[:1]:
                if alert_count >= self.max_alerts_per_cycle:
                    break
                findings.append(p)
                alert_count += 1
        
        return findings
    
    async def _check_email_breach(self, email: str) -> Dict[str, Any]:
        if not email:
            return None
        
        try:
            sha1_email = hashlib.sha1(email.encode()).hexdigest().upper()
            prefix = sha1_email[:5]
            
            response = requests.get(
                f"https://api.pwnedpasswords.com/range/{prefix}",
                timeout=10,
                headers={"User-Agent": "SwissBrain-Sentinel"}
            )
            
            suffix = sha1_email[5:]
            breached = any(suffix in line for line in response.text.splitlines())
            
            if breached:
                return self.format_finding(
                    title=f"🚨 Email comprometido",
                    content=f"Tu email aparece en al menos una filtración de datos conocida.\n\n"
                           f"🔒 *Acciones recomendadas:*\n"
                           f"1. Cambia la contraseña inmediatamente\n"
                           f"2. Activa 2FA en todas las cuentas\n"
                           f"3. Revisa actividad sospechosa\n"
                           f"4. Considera un gestor de contraseñas",
                    priority="critica",
                    metadata={"email": email, "breach_detected": True}
                )
            
        except Exception as e:
            print(f"Error verificando breach: {e}")
        
        return None
    
    async def _check_recent_vulns(self) -> List[Dict[str, Any]]:
        findings = []
        
        try:
            today = datetime.now()
            last_week = today - timedelta(days=7)
            
            response = requests.get(
                "https://services.nvd.nist.gov/rest/json/cves/2.0",
                params={
                    "pubStartDate": last_week.strftime("%Y-%m-%dT%H:%M:%S"),
                    "pubEndDate": today.strftime("%Y-%m-%dT%H:%M:%S"),
                    "cvssV3Severity": "CRITICAL"
                },
                timeout=15
            )
            
            data = response.json()
            vulns = data.get("vulnerabilities", [])[:5]
            
            for vuln in vulns:
                cve = vuln.get("cve", {})
                cve_id = cve.get("id", "CVE-UNKNOWN")
                
                # Buscar descripción en español primero
                descriptions = cve.get("descriptions", [])
                desc = "Sin descripción"
                for d in descriptions:
                    if d.get("lang") == "es":
                        desc = d.get("value", "")
                        break
                if desc == "Sin descripción" and descriptions:
                    desc = descriptions[0].get("value", "Sin descripción")
                
                metrics = cve.get("metrics", {}).get("cvssMetricV31", [{}])[0]
                score = metrics.get("cvssData", {}).get("baseScore", 0)
                
                affected = self._check_if_affects_user(desc)
                
                # >>> FIX: Mostrar vulns críticas aunque no afecten directamente
                if score >= 7.0:  # Bajar de 8.0 a 7.0
                    status_msg = "🔴 **TE AFECTA DIRECTAMENTE** — Revisa si usas esta tecnología" if affected else f"🟠 Severidad {score}/10 — Monitorear"
                else:
                    continue
                
                findings.append(self.format_finding(
                    title=f"🔴 CVE Crítico: {cve_id}",
                    content=f"📝 *Descripción:*\n{desc[:300]}...\n\n"
                           f"📊 *Severidad:* {score}/10\n"
                           f"📌 *Estado:* {status_msg}\n\n"
                           f"🔗 [Ver detalle en NVD](https://nvd.nist.gov/vuln/detail/{cve_id})",
                    priority="critica",
                    metadata={"cve_id": cve_id, "cvss_score": score, "affects_user": affected}
                ))
            
        except Exception as e:
            print(f"Error verificando CVEs: {e}")
        
        return findings
    
    async def _check_phishing_domains(self) -> List[Dict[str, Any]]:
        """CORREGIDO: Manejo de respuesta no-JSON de PhishTank."""
        findings = []
        
        try:
            response = requests.get(
                "http://data.phishtank.com/data/online-valid.json",
                timeout=15
            )
            
            # CORREGIDO: Verificar si la respuesta es JSON válido
            content_type = response.headers.get('Content-Type', '')
            if 'json' not in content_type:
                print(f"PhishTank devolvió {content_type} en lugar de JSON — saltando")
                return []
            
            # Verificar si el contenido parece HTML
            if response.text.strip().startswith('<'):
                print("PhishTank devolvió HTML — posiblemente requiere API key")
                return []
            
            data = response.json()
            
            common_targets = ["paypal", "apple", "amazon", "microsoft", "google", "bank", "hotmail"]
            
            for entry in data[:20]:
                url = entry.get("url", "").lower()
                target = entry.get("target", "").lower()
                
                if any(t in url or t in target for t in common_targets):
                    findings.append(self.format_finding(
                        title=f"🛡️ Phishing detectado: {target or 'Servicio desconocido'}",
                        content=f"Dominio malicioso detectado:\n`{url[:80]}...`\n\n"
                               f"⚠️ *NO ingreses credenciales en este sitio*\n"
                               f"El sitio legítimo es diferente\n\n"
                               f"🛡️ *Acciones:*\n"
                               f"1. Reportar: [Google Safe Browsing](https://safebrowsing.google.com/safebrowsing/report_phish/)\n"
                               f"2. Borrar el email/SMS que te llevó aquí\n"
                               f"3. Si ya ingresaste datos, cambia la contraseña",
                        priority="alta",
                        metadata={"phishing_url": url, "verified": entry.get("verified", False)}
                    ))
                    break
        
        except requests.exceptions.JSONDecodeError:
            print("PhishTank: Respuesta no es JSON válido — saltando")
        except Exception as e:
            print(f"PhishTank desactivado temporalmente: {e}")
        
        return findings
    
    def _check_if_affects_user(self, description: str) -> bool:
        user_tech = [
            "python", "django", "flask", "fastapi",
            "linux", "ubuntu", "debian",
            "docker", "kubernetes",
            "nginx", "apache",
            "postgresql", "mysql", "redis",
            "openssl", "ssh"
        ]
        desc_lower = description.lower()
        return any(tech in desc_lower for tech in user_tech)
    
    def add_monitored_email(self, email: str):
        if email not in self.monitored_emails:
            self.monitored_emails.append(email)
    
    def add_monitored_domain(self, domain: str):
        if domain not in self.monitored_domains:
            self.monitored_domains.append(domain)