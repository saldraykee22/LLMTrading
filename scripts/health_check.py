#!/usr/bin/env python3
"""
Health Check Script
====================
Comprehensive system health check for LLMTrading.
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


class HealthChecker:
    """System health checker."""

    def __init__(self):
        self.checks = []
        self.warnings = []
        self.errors = []

    def check_python_version(self) -> None:
        """Check Python version."""
        logger.info("Checking Python version...")
        
        version = sys.version_info
        if version.major == 3 and version.minor >= 10:
            self.checks.append({
                'name': 'Python Version',
                'status': 'PASS',
                'value': f'{version.major}.{version.minor}.{version.micro}'
            })
        else:
            self.errors.append({
                'name': 'Python Version',
                'status': 'FAIL',
                'value': f'{version.major}.{version.minor}.{version.micro}',
                'expected': '>= 3.10'
            })

    def check_dependencies(self) -> None:
        """Check required dependencies."""
        logger.info("Checking dependencies...")
        
        required = [
            'ccxt',
            'pandas',
            'numpy',
            'pydantic',
            'pydantic_settings',
            'langchain_core',
            'yfinance',
            'pytest',
        ]
        
        missing = []
        for package in required:
            try:
                __import__(package)
            except ImportError:
                missing.append(package)
        
        if missing:
            self.errors.append({
                'name': 'Dependencies',
                'status': 'FAIL',
                'missing': missing,
                'fix': 'pip install -r requirements.txt'
            })
        else:
            self.checks.append({
                'name': 'Dependencies',
                'status': 'PASS',
                'value': f'{len(required)} packages checked'
            })

    def check_config_files(self) -> None:
        """Check configuration files."""
        logger.info("Checking configuration files...")
        
        required_files = [
            '.env',
            'config/settings.py',
            'config/trading_params.yaml',
        ]
        
        missing = []
        for file_path in required_files:
            full_path = PROJECT_ROOT / file_path
            if not full_path.exists():
                missing.append(file_path)
        
        if missing:
            self.warnings.append({
                'name': 'Config Files',
                'status': 'WARN',
                'missing': missing,
                'note': 'Some files may be optional or generated'
            })
        else:
            self.checks.append({
                'name': 'Config Files',
                'status': 'PASS',
                'value': 'All required files present'
            })

    def check_env_variables(self) -> None:
        """Check environment variables."""
        logger.info("Checking environment variables...")
        
        import os
        required = [
            'OPENROUTER_API_KEY',
        ]
        
        missing = []
        for var in required:
            if not os.getenv(var):
                missing.append(var)
        
        if missing:
            self.warnings.append({
                'name': 'Environment Variables',
                'status': 'WARN',
                'missing': missing,
                'fix': 'Set required variables in .env file'
            })
        else:
            self.checks.append({
                'name': 'Environment Variables',
                'status': 'PASS',
                'value': 'All required variables set'
            })

    def check_directory_structure(self) -> None:
        """Check directory structure."""
        logger.info("Checking directory structure...")
        
        required_dirs = [
            'config',
            'agents',
            'data',
            'execution',
            'risk',
            'models',
            'tests',
            'utils',
        ]
        
        missing = []
        for dir_name in required_dirs:
            full_path = PROJECT_ROOT / dir_name
            if not full_path.exists() or not full_path.is_dir():
                missing.append(dir_name)
        
        if missing:
            self.errors.append({
                'name': 'Directory Structure',
                'status': 'FAIL',
                'missing': missing
            })
        else:
            self.checks.append({
                'name': 'Directory Structure',
                'status': 'PASS',
                'value': f'{len(required_dirs)} directories checked'
            })

    def check_portfolio_state(self) -> None:
        """Check portfolio state file."""
        logger.info("Checking portfolio state...")
        
        portfolio_file = PROJECT_ROOT / "data" / "portfolio_state.json"
        
        if not portfolio_file.exists():
            self.checks.append({
                'name': 'Portfolio State',
                'status': 'PASS',
                'value': 'No existing portfolio (will create on first run)'
            })
            return
        
        try:
            import json
            data = json.loads(portfolio_file.read_text())
            
            # Validate structure
            required_keys = ['initial_cash', 'cash', 'positions']
            missing_keys = [k for k in required_keys if k not in data]
            
            if missing_keys:
                self.warnings.append({
                    'name': 'Portfolio State',
                    'status': 'WARN',
                    'issue': f'Missing keys: {missing_keys}'
                })
            else:
                self.checks.append({
                    'name': 'Portfolio State',
                    'status': 'PASS',
                    'value': f"Cash: ${data['cash']:.2f}, Positions: {len(data['positions'])}"
                })
        except json.JSONDecodeError:
            self.errors.append({
                'name': 'Portfolio State',
                'status': 'FAIL',
                'issue': 'Corrupted JSON file'
            })

    def check_logs_directory(self) -> None:
        """Check logs directory."""
        logger.info("Checking logs directory...")
        
        logs_dir = PROJECT_ROOT / "logs"
        
        if not logs_dir.exists():
            logs_dir.mkdir(exist_ok=True)
            self.checks.append({
                'name': 'Logs Directory',
                'status': 'PASS',
                'value': 'Created logs directory'
            })
        else:
            # Check if writable
            test_file = logs_dir / ".write_test"
            try:
                test_file.write_text("test")
                test_file.unlink()
                self.checks.append({
                    'name': 'Logs Directory',
                    'status': 'PASS',
                    'value': 'Writable'
                })
            except Exception as e:
                self.errors.append({
                    'name': 'Logs Directory',
                    'status': 'FAIL',
                    'issue': f'Not writable: {e}'
                })

    def check_circuit_breaker_state(self) -> None:
        """Check circuit breaker state."""
        logger.info("Checking circuit breaker state...")
        
        try:
            from risk.circuit_breaker import CircuitBreaker
            cb = CircuitBreaker()
            
            # Check if circuit is open
            is_halt, reason = cb.should_halt(equity=10000.0, daily_pnl=0.0)
            
            if is_halt:
                self.warnings.append({
                    'name': 'Circuit Breaker',
                    'status': 'WARN',
                    'issue': 'Circuit breaker is OPEN',
                    'reason': reason,
                    'fix': 'Wait for reset or manually reset'
                })
            else:
                self.checks.append({
                    'name': 'Circuit Breaker',
                    'status': 'PASS',
                    'value': 'Circuit CLOSED (normal operation)'
                })
        except Exception as e:
            self.errors.append({
                'name': 'Circuit Breaker',
                'status': 'FAIL',
                'issue': str(e)
            })

    def check_system_status(self) -> None:
        """Check system status module."""
        logger.info("Checking system status...")
        
        try:
            from risk.system_status import SystemStatus
            status = SystemStatus.get_instance()
            
            if status.is_running():
                self.checks.append({
                    'name': 'System Status',
                    'status': 'PASS',
                    'value': 'RUNNING'
                })
            elif status.is_halted():
                self.warnings.append({
                    'name': 'System Status',
                    'status': 'WARN',
                    'value': 'HALTED',
                    'note': 'System was halted (emergency/cooldown)'
                })
            elif status.is_emergency():
                self.errors.append({
                    'name': 'System Status',
                    'status': 'FAIL',
                    'value': 'EMERGENCY',
                    'reason': status.get_halt_reason(),
                    'fix': 'Resolve issue and restart'
                })
        except Exception as e:
            self.errors.append({
                'name': 'System Status',
                'status': 'FAIL',
                'issue': str(e)
            })

    def run_health_check(self) -> Dict:
        """Run all health checks."""
        logger.info("=" * 60)
        logger.info("LLMTrading Health Check")
        logger.info(f"Timestamp: {datetime.now().isoformat()}")
        logger.info("=" * 60)
        
        self.check_python_version()
        self.check_dependencies()
        self.check_config_files()
        self.check_env_variables()
        self.check_directory_structure()
        self.check_portfolio_state()
        self.check_logs_directory()
        self.check_circuit_breaker_state()
        self.check_system_status()
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("HEALTH CHECK SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Passed: {len(self.checks)}")
        logger.info(f"Warnings: {len(self.warnings)}")
        logger.info(f"Errors: {len(self.errors)}")
        
        if self.checks:
            logger.info("\n✅ PASSED:")
            for check in self.checks:
                logger.info(f"  ✓ {check['name']}: {check['value']}")
        
        if self.warnings:
            logger.info(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                logger.info(f"  ⚠ {warning['name']}: {warning.get('issue', warning.get('value', ''))}")
        
        if self.errors:
            logger.info(f"\n🚨 ERRORS ({len(self.errors)}):")
            for error in self.errors:
                logger.info(f"  ✗ {error['name']}: {error.get('issue', error.get('value', ''))}")
                if 'fix' in error:
                    logger.info(f"    Fix: {error['fix']}")
        
        # Save report
        report = {
            'timestamp': datetime.now().isoformat(),
            'checks': self.checks,
            'warnings': self.warnings,
            'errors': self.errors,
            'summary': {
                'passed': len(self.checks),
                'warnings': len(self.warnings),
                'errors': len(self.errors),
                'healthy': len(self.errors) == 0
            }
        }
        
        report_file = PROJECT_ROOT / "health_check_report.json"
        report_file.write_text(json.dumps(report, indent=2))
        logger.info(f"\n📄 Full report saved to: {report_file}")
        
        # Exit code
        if self.errors:
            logger.info("\n❌ Health check FAILED")
            sys.exit(1)
        elif self.warnings:
            logger.info("\n⚠️  Health check PASSED with warnings")
            sys.exit(0)
        else:
            logger.info("\n✅ Health check PASSED")
            sys.exit(0)


def main() -> int:
    """Entry point for CLI usage."""
    checker = HealthChecker()
    checker.run_health_check()
    return 0


if __name__ == "__main__":
    main()
