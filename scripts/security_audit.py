#!/usr/bin/env python3
"""
Security Audit Script
======================
Comprehensive security check for LLMTrading system.
"""

import re
import sys
import json
import logging
from pathlib import Path
from typing import Dict

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


class SecurityAuditor:
    """Security audit checker."""

    def __init__(self):
        self.issues = []
        self.warnings = []
        self.passed = []

    def check_api_key_exposure(self) -> None:
        """Check for API key exposure in logs and code."""
        logger.info("Checking API key exposure...")
        
        # Check .env file permissions
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            if sys.platform != "win32":
                import stat
                file_stat = env_file.stat()
                if file_stat.st_mode & stat.S_IROTH:
                    self.issues.append({
                        'severity': 'CRITICAL',
                        'file': str(env_file),
                        'issue': '.env file is world-readable',
                        'fix': 'Run: chmod 600 .env'
                    })
                else:
                    self.passed.append('.env file permissions are secure')
        
        # Check for hardcoded API keys in code
        patterns = [
            r'api[_-]?key\s*[=:]\s*["\'][A-Za-z0-9]{20,}["\']',
            r'api[_-]?secret\s*[=:]\s*["\'][A-Za-z0-9]{20,}["\']',
            r'sk-[A-Za-z0-9]{32,}',
            r'binance.*key.*=.*["\'][A-Za-z0-9]{10,}',
        ]
        
        for py_file in PROJECT_ROOT.rglob("*.py"):
            if 'venv' in str(py_file) or '__pycache__' in str(py_file):
                continue
            
            try:
                content = py_file.read_text(encoding='utf-8')
                for pattern in patterns:
                    matches = re.finditer(pattern, content, re.IGNORECASE)
                    for match in matches:
                        # Check if it's in a comment or example
                        line_no = content[:match.start()].count('\n') + 1
                        line_content = content.split('\n')[line_no - 1]
                        
                        if not line_content.strip().startswith('#'):
                            self.issues.append({
                                'severity': 'CRITICAL',
                                'file': str(py_file),
                                'line': line_no,
                                'issue': 'Potential hardcoded API key',
                                'fix': 'Use environment variables instead'
                            })
            except Exception as e:
                logger.debug(f"Error checking {py_file}: {e}")
        
        logger.info(f"✓ Checked {len(list(PROJECT_ROOT.rglob('*.py')))} Python files")

    def check_injection_vulnerabilities(self) -> None:
        """Check for injection vulnerabilities."""
        logger.info("Checking injection vulnerabilities...")
        
        dangerous_patterns = [
            (r'eval\s*\(', 'eval() usage'),
            (r'exec\s*\(', 'exec() usage'),
            (r'__import__\s*\(', '__import__() usage'),
            (r'os\.system\s*\(', 'os.system() usage'),
            (r'subprocess\..*shell\s*=\s*True', 'subprocess with shell=True'),
        ]
        
        for py_file in PROJECT_ROOT.rglob("*.py"):
            if 'venv' in str(py_file) or '__pycache__' in str(py_file):
                continue
            
            try:
                content = py_file.read_text(encoding='utf-8')
                for pattern, desc in dangerous_patterns:
                    matches = list(re.finditer(pattern, content))
                    if matches:
                        # Check if it's in a safe context
                        for match in matches:
                            line_no = content[:match.start()].count('\n') + 1
                            content.split('\n')[line_no - 1]
                            
                            # Allow in tests or if properly sanitized
                            if 'test' not in str(py_file).lower():
                                self.warnings.append({
                                    'severity': 'MEDIUM',
                                    'file': str(py_file),
                                    'line': line_no,
                                    'issue': desc,
                                    'fix': 'Ensure input is sanitized or use safer alternatives'
                                })
            except Exception as e:
                logger.debug(f"Error checking {py_file}: {e}")

    def check_sql_injection(self) -> None:
        """Check for SQL injection vulnerabilities."""
        logger.info("Checking SQL injection vulnerabilities...")
        
        # SQL injection patterns
        patterns = [
            r'execute\s*\(\s*f["\']',  # f-string in SQL execute
            r'execute\s*\(\s*["\'].*%s.*%.*\(',  # % formatting in SQL
            r'raw\s*\(\s*f["\']',  # f-string in raw SQL
        ]
        
        for py_file in PROJECT_ROOT.rglob("*.py"):
            if 'venv' in str(py_file):
                continue
            
            try:
                content = py_file.read_text(encoding='utf-8')
                for pattern in patterns:
                    if re.search(pattern, content):
                        line_no = content[:content.find(re.search(pattern, content).group())].count('\n') + 1
                        self.issues.append({
                            'severity': 'HIGH',
                            'file': str(py_file),
                            'line': line_no,
                            'issue': 'Potential SQL injection',
                            'fix': 'Use parameterized queries'
                        })
            except Exception as e:
                logger.debug(f"Error checking {py_file}: {e}")

    def check_file_permissions(self) -> None:
        """Check sensitive file permissions."""
        logger.info("Checking file permissions...")
        
        sensitive_files = [
            '.env',
            'config/credentials.json',
            'data/portfolio_state.json',
        ]
        
        for file_path in sensitive_files:
            full_path = PROJECT_ROOT / file_path
            if full_path.exists() and sys.platform != "win32":
                import stat
                file_stat = full_path.stat()
                
                if file_stat.st_mode & stat.S_IROTH:
                    self.warnings.append({
                        'severity': 'MEDIUM',
                        'file': str(full_path),
                        'issue': 'File is world-readable',
                        'fix': f'Run: chmod 600 {file_path}'
                    })

    def check_logging_security(self) -> None:
        """Check for sensitive data in logs."""
        logger.info("Checking logging security...")
        
        patterns = [
            (r'logger\..*password', 'Logging password'),
            (r'logger\..*secret', 'Logging secret'),
            (r'logger\..*api.?key', 'Logging API key'),
            (r'print\(.*password', 'Printing password'),
            (r'print\(.*secret', 'Printing secret'),
        ]
        
        for py_file in PROJECT_ROOT.rglob("*.py"):
            if 'venv' in str(py_file):
                continue
            
            try:
                content = py_file.read_text(encoding='utf-8')
                for pattern, desc in patterns:
                    matches = re.finditer(pattern, content, re.IGNORECASE)
                    for match in matches:
                        line_no = content[:match.start()].count('\n') + 1
                        line_content = content.split('\n')[line_no - 1]
                        
                        # Check if it's masking the value
                        if '***' not in line_content and 'mask' not in line_content.lower():
                            self.warnings.append({
                                'severity': 'LOW',
                                'file': str(py_file),
                                'line': line_no,
                                'issue': desc,
                                'fix': 'Mask sensitive values before logging'
                            })
            except Exception as e:
                logger.debug(f"Error checking {py_file}: {e}")

    def check_dependencies(self) -> None:
        """Check for known vulnerable dependencies."""
        logger.info("Checking dependencies...")
        
        requirements_file = PROJECT_ROOT / "requirements.txt"
        if not requirements_file.exists():
            self.warnings.append({
                'severity': 'LOW',
                'file': str(requirements_file),
                'issue': 'requirements.txt not found',
                'fix': 'Create requirements.txt with pinned versions'
            })
            return
        
        # Check for unpinned versions
        content = requirements_file.read_text()
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                if '==' not in line and '>=' not in line:
                    self.warnings.append({
                        'severity': 'LOW',
                        'file': str(requirements_file),
                        'issue': f'Unpinned dependency: {line}',
                        'fix': 'Pin to specific version (e.g., package==1.2.3)'
                    })

    def run_audit(self) -> Dict:
        """Run all security checks."""
        logger.info("=" * 60)
        logger.info("LLMTrading Security Audit")
        logger.info("=" * 60)
        
        self.check_api_key_exposure()
        self.check_injection_vulnerabilities()
        self.check_sql_injection()
        self.check_file_permissions()
        self.check_logging_security()
        self.check_dependencies()
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("AUDIT SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Issues: {len(self.issues)}")
        logger.info(f"Warnings: {len(self.warnings)}")
        logger.info(f"Passed: {len(self.passed)}")
        
        if self.issues:
            logger.info("\n🚨 CRITICAL/HIGH ISSUES:")
            for issue in self.issues:
                logger.info(f"  [{issue['severity']}] {issue['file']}:{issue.get('line', '?')}")
                logger.info(f"    Issue: {issue['issue']}")
                logger.info(f"    Fix: {issue['fix']}")
        
        if self.warnings:
            logger.info(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings[:10]:  # Show first 10
                logger.info(f"  [{warning['severity']}] {warning['file']}:{warning.get('line', '?')}")
                logger.info(f"    Issue: {warning['issue']}")
        
        if self.passed:
            logger.info(f"\n✅ PASSED CHECKS ({len(self.passed)}):")
            for check in self.passed:
                logger.info(f"  ✓ {check}")
        
        # Save report
        report = {
            'timestamp': str(Path.ctime(PROJECT_ROOT)),
            'issues': self.issues,
            'warnings': self.warnings,
            'passed': self.passed,
            'summary': {
                'total_issues': len(self.issues),
                'total_warnings': len(self.warnings),
                'total_passed': len(self.passed),
            }
        }
        
        report_file = PROJECT_ROOT / "security_audit_report.json"
        report_file.write_text(json.dumps(report, indent=2))
        logger.info(f"\n📄 Full report saved to: {report_file}")
        
        # Exit code
        if self.issues:
            sys.exit(1)
        else:
            logger.info("\n✅ Security audit PASSED")
            sys.exit(0)


if __name__ == "__main__":
    auditor = SecurityAuditor()
    auditor.run_audit()
