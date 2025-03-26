import zipfile
import json
from rapidfuzz import process, fuzz
import csv
from datetime import datetime

def create_cik_mapping(zip_path: str, output_csv: str) -> None:
    """
    Extract CIK and entity names from JSON files in a ZIP and save to CSV.
    """
    with zipfile.ZipFile(zip_path, 'r') as z:
        with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['cik', 'entity_name', 'filename'])
            for fileinfo in z.infolist():
                if not fileinfo.filename.endswith('.json'):
                    continue
                try:
                    with z.open(fileinfo) as jsonfile:
                        data = json.load(jsonfile)
                        writer.writerow([data['cik'], data['entityName'],fileinfo.filename])
                except (KeyError, json.JSONDecodeError) as e:
                    print(f"Skipped {fileinfo.filename}: {str(e)}")

class CIKLookup:
    def __init__(self, csv_path: str):
        self.entity_names = []
        self.cik_map = {}
        self.file_map = {}
        
        # Load data from CSV
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                normalized_name = row['entity_name'].strip().lower()
                self.entity_names.append(normalized_name)
                self.cik_map[normalized_name] = row['cik']
                self.file_map[normalized_name] = row['filename']
                
    
    def find_cik(self, search_term: str, score_cutoff: int = 80) -> dict:
        """
        Find CIK with exact or fuzzy matches.
        Returns: {'cik': '1750', 'match_type': 'exact'/'fuzzy', 'score': 100}
        """
        normalized_search = search_term.strip().lower()
        
        # Check exact match first
        if normalized_search in self.cik_map:
            return {
                'cik': self.cik_map[normalized_search],
                'match_type': 'exact',
                'filename': self.file_map[normalized_search],
                'score': 100
            }
        
        # Fuzzy match using RapidFuzz
        result = process.extractOne(
            normalized_search,
            self.entity_names,
            scorer=fuzz.WRatio,  # Weighted ratio (good for typos and abbreviations)
            score_cutoff=score_cutoff
        )
        
        if result:
            matched_name, score, _ = result
            return {
                'cik': self.cik_map[matched_name],
                'filename': self.file_map[matched_name],
                'match_type': 'fuzzy',
                'score': score
            }
        
        return {'cik': None, 'match_type': 'no_match', 'score': 0}

class SECRiskAnalyzer:
    def __init__(self, json_data):
        self.data = json_data
        self.risks = {
            'auditor_changes': [],
            'legal_proceedings': [],
            'restatements': False,
            'material_weakness': False,
            'debt_ratios': {},
            'revenue_trend': None,
            'related_party_transactions': [],
            'going_concern': False
        }

    def analyze(self):
        """Run all risk checks"""
        self._check_auditor_changes()
        self._check_legal_proceedings()
        self._check_financial_restatements()
        self._check_material_weakness()
        self._calculate_debt_ratios()
        self._analyze_revenue_trend()
        self._check_related_party_transactions()
        self._check_going_concern()
        return self.risks

    def _check_auditor_changes(self):
        """Check for frequent auditor changes (>1 in 3 years)"""
        auditor_data = self.data.get('facts', {}).get('us-gaap', {}).get(
            'AuditorFirmEngagementTerminationDate', {}
        ).get('units', {}).get('USD', [])
        
        changes = [item['val'] for item in auditor_data 
                 if datetime.strptime(item['end'], '%Y-%m-%d').year >= datetime.now().year - 3]
        self.risks['auditor_changes'] = changes
        self.risks['auditor_change_risk'] = len(changes) > 1

    def _check_legal_proceedings(self):
        """Identify material legal proceedings"""
        legal = self.data.get('facts', {}).get('us-gaap', {}).get(
            'LegalProceedings', {}
        ).get('units', {}).get('USD', [])
        
        self.risks['legal_proceedings'] = [
            p for p in legal 
            if p.get('isMaterial', False) and p['val'] > 1000000  # $1M+ material cases
        ]

    def _check_financial_restatements(self):
        """Detect financial restatements"""
        self.risks['restatements'] = any(
            note.get('description', '').lower().contains('restatement')
            for note in self.data.get('notes', [])
        )

    def _calculate_debt_ratios(self):
        """Calculate debt-to-equity ratio (risk if >2)"""
        try:
            liabilities = self.data['facts']['us-gaap']['Liabilities']['units']['USD'][-1]['val']
            equity = self.data['facts']['us-gaap']['StockholdersEquity']['units']['USD'][-1]['val']
            self.risks['debt_ratios']['debt_to_equity'] = liabilities / equity
        except (KeyError, IndexError):
            pass

    def _analyze_revenue_trend(self):
        """3-year revenue trend analysis"""
        revenues = self.data['facts']['us-gaap']['RevenueFromContractWithCustomerExcludingAssessedTax']['units']['USD']
        if len(revenues) >= 4:  # Need at least 4 quarters
            latest = revenues[-4:]
            trend = (latest[-1]['val'] - latest[0]['val']) / latest[0]['val']
            self.risks['revenue_trend'] = 'declining' if trend < -0.15 else 'stable'

    def get_risk_summary(self):
        """Generate human-readable summary"""
        summary = []
        if self.risks['auditor_change_risk']:
            summary.append(f"Auditor changed {len(self.risks['auditor_changes'])} times in 3 years")
        if self.risks['legal_proceedings']:
            summary.append(f"{len(self.risks['legal_proceedings'])} material legal cases")
        if self.risks['debt_ratios'].get('debt_to_equity', 0) > 2:
            summary.append(f"High debt-to-equity ratio: {self.risks['debt_ratios']['debt_to_equity']:.1f}")
        return summary

    def _check_material_weakness(self):
        """Check for reported material weaknesses in internal controls"""
        try:
            disclosures = self.data['facts']['us-gaap']['MaterialWeakness']['units']['USD']
            self.risks['material_weakness'] = any(
                item['val'] == True 
                for item in disclosures
                if 'val' in item
            )
        except KeyError:
            self.risks['material_weakness'] = False

    def _check_related_party_transactions(self):
        """Identify related party transactions"""
        try:
            rpt = self.data['facts']['us-gaap']['RelatedPartyTransactions']['units']['USD']
            self.risks['related_party_transactions'] = [
                txn for txn in rpt
                if txn.get('isRelatedParty', False)
            ]
        except KeyError:
            self.risks['related_party_transactions'] = []

    def _check_going_concern(self):
        """Check for going concern warnings"""
        self.risks['going_concern'] = any(
            'substantial doubt' in note.get('text', '').lower()
            for note in self.data.get('notes', [])
            if note.get('title', '') == 'BasisOfAccounting'
        )
    
# create_cik_mapping('/home/nithish/home/applAI/aidel-llmao/code/src/companyfacts.zip', 'cik_mapping.csv')