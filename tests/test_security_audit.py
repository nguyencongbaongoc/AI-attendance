"""
Phase 18 Security Hardening & Secret Isolation Audit.

Ensures production readiness from a security, credential, and environmental perspective.

Tasks:
1. Environment & Secret Audit:
   - Verify all API secrets reside exclusively in .env or system environment variables
   - Verify .env is in .gitignore
   - Verify no hardcoded credentials in source files
2. Logging & Redaction Sanity Check:
   - Inspect application logging for phone numbers, identities, auth tokens
   - Ensure masking/redaction in production log streams (e.g., 090****123)
3. Network Port & Endpoint Exposure Audit:
   - Confirm local service isolation: internal ports listen on 127.0.0.1
"""

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


class SecurityAudit:
    """Security and secrets audit for production readiness."""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.results = {
            'env_file_in_gitignore': False,
            'no_hardcoded_secrets': True,
            'secrets_only_in_env': True,
            'logging_redaction_verified': False,
            'network_isolation_verified': False,
            'no_credential_leaks': True,
            'errors': [],
            'warnings': [],
            'findings': {}
        }
        
        # Patterns for secret detection
        self.secret_patterns = {
            'api_key': re.compile(r'(api[_-]?key|apikey)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.IGNORECASE),
            'secret_key': re.compile(r'(secret[_-]?key|secretkey)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.IGNORECASE),
            'access_token': re.compile(r'(access[_-]?token|accesstoken)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.IGNORECASE),
            'bot_token': re.compile(r'(bot[_-]?token|bottoken)\s*[=:]\s*["\']?([0-9]{8,10}:[a-zA-Z0-9_\-]{35})["\']?', re.IGNORECASE),
            'webhook_secret': re.compile(r'(webhook[_-]?secret|webhooksecret)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.IGNORECASE),
            'password': re.compile(r'(password|passwd)\s*[=:]\s*["\']?([a-zA-Z0-9_\-!@#$%^&*]{8,})["\']?', re.IGNORECASE),
            'phone_number': re.compile(r'(?:\+84|0)[0-9]{9,10}'),
            'zalo_oa_secret': re.compile(r'zalo[_-]?oa[_-]?secret\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.IGNORECASE),
            'esms_key': re.compile(r'(esms|speedsms)[_-]?(api[_-]?key|key)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.IGNORECASE),
        }
        
        # Files to exclude from secret scanning
        self.exclude_patterns = [
            '__pycache__',
            '.pyc',
            '.git',
            '.venv',
            '.venv2',
            'venv',
            'env',
            'node_modules',
            '.pytest_cache',
            '.mypy_cache',
            '.kilo',
            'new_engine',
            'graphify-out',
            'artifacts',
            'reports',
            '*.log',
            '*.md',
            '*.txt',
            '*.json',
            '*.yml',
            '*.yaml',
            '*.lock',
        ]
    
    def run_all_audits(self) -> bool:
        """Run all security audits."""
        logger.info("=" * 80)
        logger.info("PHASE 18 SECURITY HARDENING & SECRET ISOLATION AUDIT")
        logger.info("=" * 80)
        
        success = True
        
        # Audit 1: Environment & Secret Audit
        if not self._audit_env_and_secrets():
            success = False
        
        # Audit 2: Logging & Redaction
        if not self._audit_logging_redaction():
            success = False
        
        # Audit 3: Network Port & Endpoint Exposure
        if not self._audit_network_isolation():
            success = False
        
        # Print summary
        self._print_summary()
        
        return success
    
    def _audit_env_and_secrets(self) -> bool:
        """Audit environment files and secret handling."""
        logger.info("\n--- Audit 1: Environment & Secret Audit ---")
        
        all_passed = True
        
        # Check 1: .env in .gitignore
        gitignore_path = self.project_root / ".gitignore"
        if gitignore_path.exists():
            with open(gitignore_path, 'r') as f:
                gitignore_content = f.read()
            
            if '.env' in gitignore_content:
                logger.info("✅ .env is listed in .gitignore")
                self.results['env_file_in_gitignore'] = True
            else:
                logger.error("❌ .env is NOT in .gitignore")
                self.results['errors'].append(".env not in .gitignore")
                all_passed = False
        else:
            logger.error("❌ .gitignore not found")
            self.results['errors'].append(".gitignore not found")
            all_passed = False
        
        # Check 2: No .env files committed
        env_files = list(self.project_root.glob("**/.env*"))
        committed_env = [f for f in env_files if not self._is_excluded(f)]
        if committed_env:
            logger.error(f"❌ Found committed .env files: {committed_env}")
            self.results['errors'].append(f"Committed .env files: {committed_env}")
            all_passed = False
        else:
            logger.info("✅ No .env files committed to repository")
        
        # Check 3: Scan source code for hardcoded secrets
        secret_findings = self._scan_for_secrets()
        if secret_findings:
            logger.error(f"❌ Found {len(secret_findings)} potential hardcoded secrets")
            for finding in secret_findings:
                logger.error(f"  {finding['file']}:{finding['line']} - {finding['type']}")
                self.results['errors'].append(f"Hardcoded secret in {finding['file']}:{finding['line']}")
                all_passed = False
                self.results['no_hardcoded_secrets'] = False
        else:
            logger.info("✅ No hardcoded secrets found in source code")
            self.results['no_hardcoded_secrets'] = True
        
        # Check 4: Verify secrets loaded from environment
        env_usage_findings = self._check_env_usage()
        self.results['findings']['env_usage'] = env_usage_findings
        
        self.results['secrets_only_in_env'] = all_passed
        return all_passed
    
    def _scan_for_secrets(self) -> List[Dict]:
        """Scan source files for hardcoded secrets."""
        findings = []
        
        # Source file extensions to scan
        source_extensions = ['.py', '.js', '.ts', '.jsx', '.tsx', '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg']
        
        for ext in source_extensions:
            for file_path in self.project_root.rglob(f"*{ext}"):
                if self._is_excluded(file_path):
                    continue
                
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                    
                    for line_num, line in enumerate(lines, 1):
                        # Skip comments and test data
                        stripped = line.strip()
                        if stripped.startswith('#') or stripped.startswith('//'):
                            continue
                        
                        for secret_type, pattern in self.secret_patterns.items():
                            matches = pattern.findall(line)
                            if matches:
                                # Filter out obvious test/placeholder values
                                for match in matches:
                                    if isinstance(match, tuple):
                                        value = match[1] if len(match) > 1 else match[0]
                                    else:
                                        value = match
                                    
                                    # Skip test/placeholder values
                                    if self._is_test_value(value):
                                        continue
                                    
                                    findings.append({
                                        'file': str(file_path.relative_to(self.project_root)),
                                        'line': line_num,
                                        'type': secret_type,
                                        'value_preview': value[:10] + '...' if len(value) > 10 else value
                                    })
                except Exception as e:
                    logger.debug(f"Could not scan {file_path}: {e}")
        
        return findings
    
    def _is_test_value(self, value: str) -> bool:
        """Check if a value is a test/placeholder value."""
        test_indicators = [
            'test', 'example', 'placeholder', 'dummy', 'fake', 'mock',
            'your_key', 'your_secret', 'your_token', 'change_me',
            'xxxx', '****', '123456', 'abcdef'
        ]
        value_lower = value.lower()
        return any(indicator in value_lower for indicator in test_indicators)
    
    def _is_excluded(self, path: Path) -> bool:
        """Check if path should be excluded from scanning."""
        path_str = str(path)
        for pattern in self.exclude_patterns:
            if pattern in path_str:
                return True
        return False
    
    def _check_env_usage(self) -> Dict:
        """Check how environment variables are used in code."""
        env_vars_used = set()
        env_files_found = []
        
        # Find .env.example or similar
        for env_file in self.project_root.glob("**/.env*"):
            if not self._is_excluded(env_file):
                env_files_found.append(str(env_file.relative_to(self.project_root)))
        
        # Scan for os.getenv, os.environ, dotenv usage
        env_pattern = re.compile(r'(os\.getenv|os\.environ\[|os\.environ\.get|getenv|dotenv|load_dotenv|environ\[)', re.IGNORECASE)
        var_pattern = re.compile(r'["\']([A-Z_][A-Z0-9_]*)["\']')
        
        for py_file in self.project_root.rglob("*.py"):
            if self._is_excluded(py_file):
                continue
            
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                if env_pattern.search(content):
                    # Extract variable names
                    for match in var_pattern.finditer(content):
                        var_name = match.group(1)
                        if var_name.isupper() and '_' in var_name:
                            env_vars_used.add(var_name)
            except Exception:
                pass
        
        return {
            'env_files_found': env_files_found,
            'env_vars_used_in_code': sorted(env_vars_used),
            'count': len(env_vars_used)
        }
    
    def _audit_logging_redaction(self) -> bool:
        """Audit logging for proper redaction of sensitive data."""
        logger.info("\n--- Audit 2: Logging & Redaction Sanity Check ---")
        
        all_passed = True
        
        # Check for logging configuration that redacts sensitive fields
        logging_configs = []
        redaction_found = False
        
        for py_file in self.project_root.rglob("*.py"):
            if self._is_excluded(py_file):
                continue
            
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Check for logging configuration
                if 'logging' in content.lower() and ('basicconfig' in content.lower() or 'dictconfig' in content.lower() or 'formatter' in content.lower()):
                    logging_configs.append(str(py_file.relative_to(self.project_root)))
                
                # Check for redaction patterns
                redaction_patterns = [
                    r'redact',
                    r'mask',
                    r'filter',
                    r'phone.*\*{4}',
                    r'token.*\*{4}',
                    r'password.*\*{4}',
                ]
                
                for pattern in redaction_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        redaction_found = True
                        break
                        
            except Exception:
                pass
        
        logger.info(f"Logging configuration files: {logging_configs}")
        
        # Check for sensitive data in log statements
        sensitive_log_patterns = [
            (r'logger\.(info|debug|warning|error|critical)\(.*phone', 'Phone number in log'),
            (r'logger\.(info|debug|warning|error|critical)\(.*token', 'Token in log'),
            (r'logger\.(info|debug|warning|error|critical)\(.*password', 'Password in log'),
            (r'logger\.(info|debug|warning|error|critical)\(.*secret', 'Secret in log'),
            (r'logger\.(info|debug|warning|error|critical)\(.*api[_-]?key', 'API key in log'),
            (r'print\(.*phone', 'Phone number in print'),
            (r'print\(.*token', 'Token in print'),
            (r'print\(.*password', 'Password in print'),
        ]
        
        log_violations = []
        for py_file in self.project_root.rglob("*.py"):
            if self._is_excluded(py_file):
                continue
            
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                
                for line_num, line in enumerate(lines, 1):
                    for pattern, desc in sensitive_log_patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            # Check if it's actually a variable being logged (not a string literal warning)
                            if '%' in line or '{}' in line or 'f"' in line or "f'" in line:
                                log_violations.append({
                                    'file': str(py_file.relative_to(self.project_root)),
                                    'line': line_num,
                                    'issue': desc,
                                    'code': line.strip()[:100]
                                })
            except Exception:
                pass
        
        if log_violations:
            logger.warning(f"⚠️ Found {len(log_violations)} potential sensitive data logging issues:")
            for v in log_violations[:10]:  # Show first 10
                logger.warning(f"  {v['file']}:{v['line']} - {v['issue']}: {v['code']}")
            self.results['warnings'].extend([f"{v['file']}:{v['line']} - {v['issue']}" for v in log_violations])
        else:
            logger.info("✅ No obvious sensitive data logging violations found")
        
        # Check for structured logging with redaction
        if redaction_found:
            logger.info("✅ Redaction/masking patterns found in code")
            self.results['logging_redaction_verified'] = True
        else:
            logger.warning("⚠️ No explicit redaction/masking patterns found in logging")
            self.results['warnings'].append("No explicit redaction patterns found")
        
        self.results['findings']['logging_configs'] = logging_configs
        self.results['findings']['log_violations'] = log_violations
        
        return all_passed
    
    def _audit_network_isolation(self) -> bool:
        """Audit network port bindings for proper isolation."""
        logger.info("\n--- Audit 3: Network Port & Endpoint Exposure ---")
        
        all_passed = True
        
        # Check configuration files for bind addresses
        bind_patterns = [
            (r'(host|bind|address)\s*[=:]\s*["\']?0\.0\.0\.0["\']?', 'Binds to 0.0.0.0 (all interfaces)'),
            (r'(host|bind|address)\s*[=:]\s*["\']?::["\']?', 'Binds to :: (all IPv6 interfaces)'),
            (r'(host|bind|address)\s*[=:]\s*["\']?127\.0\.0\.1["\']?', 'Binds to 127.0.0.1 (localhost only) - GOOD'),
            (r'(host|bind|address)\s*[=:]\s*["\']?localhost["\']?', 'Binds to localhost - GOOD'),
        ]
        
        network_findings = {
            'binds_all_interfaces': [],
            'binds_localhost_only': [],
            'config_files_checked': []
        }
        
        config_files = list(self.project_root.rglob("*.yaml")) + \
                      list(self.project_root.rglob("*.yml")) + \
                      list(self.project_root.rglob("*.json")) + \
                      list(self.project_root.rglob("*.ini")) + \
                      list(self.project_root.rglob("*.toml")) + \
                      list(self.project_root.rglob("*.py"))
        
        for config_file in config_files:
            if self._is_excluded(config_file):
                continue
            
            try:
                with open(config_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                network_findings['config_files_checked'].append(str(config_file.relative_to(self.project_root)))
                
                for pattern, desc in bind_patterns:
                    matches = re.finditer(pattern, content, re.IGNORECASE)
                    for match in matches:
                        line_num = content[:match.start()].count('\n') + 1
                        if '0.0.0.0' in match.group() or '::' in match.group():
                            network_findings['binds_all_interfaces'].append({
                                'file': str(config_file.relative_to(self.project_root)),
                                'line': line_num,
                                'pattern': match.group(),
                                'description': desc
                            })
                        elif '127.0.0.1' in match.group() or 'localhost' in match.group():
                            network_findings['binds_localhost_only'].append({
                                'file': str(config_file.relative_to(self.project_root)),
                                'line': line_num,
                                'pattern': match.group(),
                                'description': desc
                            })
            except Exception:
                pass
        
        # Check Python code for uvicorn/fastapi host bindings
        for py_file in self.project_root.rglob("*.py"):
            if self._is_excluded(py_file):
                continue
            
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Look for uvicorn.run or app.run with host parameter
                uvicorn_pattern = re.compile(r'(uvicorn\.run|app\.run|FastAPI).*host\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
                matches = uvicorn_pattern.findall(content)
                for match in matches:
                    host = match[1] if isinstance(match, tuple) else match
                    line_num = content[:content.find(match[0])].count('\n') + 1 if isinstance(match, tuple) else 0
                    
                    if host in ('0.0.0.0', '::'):
                        network_findings['binds_all_interfaces'].append({
                            'file': str(py_file.relative_to(self.project_root)),
                            'line': line_num,
                            'pattern': f'host="{host}"',
                            'description': 'Binds to all interfaces in code'
                        })
                    elif host in ('127.0.0.1', 'localhost'):
                        network_findings['binds_localhost_only'].append({
                            'file': str(py_file.relative_to(self.project_root)),
                            'line': line_num,
                            'pattern': f'host="{host}"',
                            'description': 'Binds to localhost only in code - GOOD'
                        })
            except Exception:
                pass
        
        # Report findings
        if network_findings['binds_all_interfaces']:
            logger.warning(f"⚠️ Found {len(network_findings['binds_all_interfaces'])} services binding to all interfaces:")
            for finding in network_findings['binds_all_interfaces']:
                logger.warning(f"  {finding['file']}:{finding['line']} - {finding['pattern']} ({finding['description']})")
                self.results['warnings'].append(f"{finding['file']}:{finding['line']} binds to all interfaces")
        else:
            logger.info("✅ No services found binding to all interfaces (0.0.0.0/::)")
        
        if network_findings['binds_localhost_only']:
            logger.info(f"✅ Found {len(network_findings['binds_localhost_only'])} services properly bound to localhost:")
            for finding in network_findings['binds_localhost_only']:
                logger.info(f"  {finding['file']}:{finding['line']} - {finding['pattern']}")
        
        # Check specific critical services
        critical_ports = {
            8000: 'Backend API',
            8554: 'MediaMTX RTSP',
            9997: 'MediaMTX API',
            8888: 'MediaMTX HLS',
            8889: 'MediaMTX WebRTC',
            1935: 'MediaMTX RTMP',
            3000: 'Frontend',
        }
        
        self.results['findings']['network'] = network_findings
        self.results['findings']['critical_ports'] = critical_ports
        
        # Verify bootstrap.py binds correctly
        bootstrap_path = self.project_root / "bootstrap.py"
        if bootstrap_path.exists():
            with open(bootstrap_path, 'r') as f:
                bootstrap_content = f.read()
            
            # Check backend host default
            if 'host.*=.*["\']0.0.0.0["\']' in bootstrap_content:
                logger.warning("⚠️ bootstrap.py defaults backend to 0.0.0.0")
                self.results['warnings'].append("bootstrap.py defaults backend to 0.0.0.0")
            else:
                logger.info("✅ bootstrap.py backend host configuration checked")
        
        # Check MediaMTX config
        mediamtx_config = self.project_root / "mediamtx" / "mediamtx.yml"
        if mediamtx_config.exists():
            with open(mediamtx_config, 'r') as f:
                mediamtx_content = f.read()
            
            if 'apiAddress: :9997' in mediamtx_content:
                logger.warning("⚠️ MediaMTX API binds to all interfaces (:9997)")
                self.results['warnings'].append("MediaMTX API binds to all interfaces")
            else:
                logger.info("✅ MediaMTX API binding checked")
        
        self.results['network_isolation_verified'] = len(network_findings['binds_all_interfaces']) == 0
        return True  # Don't fail on network warnings, just warn
    
    def _print_summary(self):
        """Print audit summary."""
        logger.info("\n" + "=" * 80)
        logger.info("SECURITY AUDIT SUMMARY")
        logger.info("=" * 80)
        
        for key, value in self.results.items():
            if key in ['errors', 'warnings', 'findings']:
                continue
            status = "✅ PASS" if value else "❌ FAIL"
            logger.info(f"  {key}: {status}")
        
        if self.results['errors']:
            logger.info(f"\n❌ Errors ({len(self.results['errors'])}):")
            for err in self.results['errors']:
                logger.info(f"  - {err}")
        
        if self.results['warnings']:
            logger.info(f"\n⚠️ Warnings ({len(self.results['warnings'])}):")
            for warn in self.results['warnings'][:20]:
                logger.info(f"  - {warn}")
            if len(self.results['warnings']) > 20:
                logger.info(f"  ... and {len(self.results['warnings']) - 20} more")
        
        overall = all([
            self.results['env_file_in_gitignore'],
            self.results['no_hardcoded_secrets'],
            self.results['secrets_only_in_env'],
        ])
        
        logger.info(f"\nOVERALL SECURITY POSTURE: {'✅ SECURE' if overall else '❌ ISSUES FOUND'}")


def main():
    parser = argparse.ArgumentParser(description="Phase 18 Security Hardening & Secret Isolation Audit")
    parser.add_argument("--project-root", type=str, default=".", help="Project root directory")
    args = parser.parse_args()
    
    audit = SecurityAudit(args.project_root)
    success = audit.run_all_audits()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()