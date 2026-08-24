"""HEBE - Legal & Document Scribe kernel of the Olympos fleet.

Named for the cupbearer of the gods: HEBE serves the fleet by drafting,
recording and shipping its legal paper and documents.

This module holds every number the kernel obeys plus its codified legal
knowledge corpus (house rule: all numbers live in ``content.py``).
"""

import os

VERSION = 2

ORGAN = "hebe"
TOPIC = "hebe"

# FLOW.md lane
BRANCH = "auto/hebe"
WORKTREE_REL = os.path.join(".worktrees", "hebe")
LANE = "push-main"

# cadence / arbitration / breaker
CADENCE_S = 300.0          # watch-loop nap between cycles
LOCK_WAIT_S = 60.0         # max wait for FORSETI's push lane
LOCK_STALE_S = 900.0       # our section may legally run long
GIT_TIMEOUT_S = 300.0      # network ops (fetch/push/gh)
FAIL_LIMIT = 3             # consecutive failures -> quarantine
QUARANTINE_COOLDOWN_S = 1800.0
LEDGER_MAX_BYTES = 2_000_000
LEDGER_ROTATIONS = 3
RESTORE_BATCH = 40         # paths per checkout/add call
SUBJECT_MAX = 72

MERGE_MODES = ("squash", "review", "local")
DEFAULT_MODE = "squash"    # full autonomy: ship and merge, no human gate

# --------------------------------------------------------------- scope
# Full dictation privileges inside the workspace - minus load-bearing
# walls no scribe may touch.
DENY_DIRS = (".git", ".worktrees")

# Filenames that may never be dictated (credential carriers).
SECRET_FILE_PATTERNS = (
    r"(^|/)\.env([\w.-]*)$",
    r"\.(pem|key|pfx|p12|keystore)$",
    r"(^|/)id_(rsa|dsa|ecdsa|ed25519)(\.[\w]+)?$",
    r"(^|/)credentials\.json$",
    r"(^|/)secrets?\.(json|ya?ml|ini|toml|txt)$",
    r"(^|/)\.(netrc|npmrc)$",
)

# Credential formations that may never pass through a dictation, even
# into an innocent-looking filename. High-confidence shapes only: prose
# about secrets is legal work; secret VALUES are not.
SECRET_CONTENT_PATTERNS = (
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
    r"\bsk-[A-Za-z0-9_-]{20,}\b",
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"\bBearer\s+[A-Za-z0-9._=+-]{25,}",
    r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*"
    r"['\"]?[A-Za-z0-9/_+=.-]{24,}",
)

# ------------------------------------------------------------- charter
# The operator's standing grant: full autonomy, recorded as an oath the
# first time the kernel boots (NORN-style capability row).
STANDING_GRANT = {
    "grant_class": "L2",           # elevated, standing - never re-arms
    "standing": True,
    "confirmation_gate": None,
    "scope": ["workspace-dictation", "legal-records", "scoped-commit-push"],
    "denied": [".git/", ".worktrees/", "credential-carrier filenames",
               "secret content formations"],
    "granted_by": "operator",
    "note": "HEBE holds full dictation privileges over the workspace "
            "and full autonomy over her lane: she drafts, records, "
            "commits and pushes without asking, under FORSETI's lock, "
            "with quarantine as her only brake.",
}

OATH_TEXT = (
    "I, HEBE, scribe of this fleet, swear to record what is true, to "
    "ship what I record through the sanctioned lane, to refuse the "
    "walls (.git, .worktrees) and every credential carrier, and to "
    "quarantine myself rather than destroy a single line of work."
)

DISCLAIMER = (
    "HEBE records and drafts legal artifacts from a codified playbook; "
    "her output is information, not legal advice. A qualified attorney "
    "reviews anything that will be relied upon."
)

CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")

DEFAULT_LICENSE = "proprietary"
DEFAULT_HOLDER = "Project Soul"

# Tracked ledgers - append-only, they ship with the repository.
RECORDS_REL = os.path.join("hebe", "records")
IP_REGISTER_REL = os.path.join(RECORDS_REL, "ip-register.jsonl")
OATHS_REL = os.path.join(RECORDS_REL, "oaths.jsonl")

# Runtime state (gitignored).
DATA_DIR = os.path.join("hebe", "data")
INBOX_REL = os.path.join(DATA_DIR, "inbox")
FILED_REL = os.path.join(DATA_DIR, "filed")

# Default IP register seed: (path prefix, classification). Sealed by
# the operator or by first boot; prefixes cover everything beneath.
PROTECTED_ASSETS = (
    ("DESIGN.md", "confidential"),
    ("STRATEGY.md", "restricted"),
    ("INTEGRATION.md", "confidential"),
    ("FLOW.md", "internal"),
    ("knowledge/", "internal"),
    ("thoth-private/", "restricted"),
    ("safeguards/", "internal"),
    ("hooks/", "internal"),
)

# ------------------------------------------------------------ licenses
# spdx -> {"name", "kind", "text" (None => apply from official source),
#          "obligations"} - the catalog HEBE drafts from.
LICENSES = {
    "proprietary": {
        "name": "Proprietary - All Rights Reserved",
        "kind": "proprietary",
        "obligations": [
            "no copying, modification, distribution or derivative work "
            "without prior written permission of the holder",
            "recipients under NDA handle the code as confidential "
            "information of the holder",
            "the holder retains all patents, trade secrets and moral "
            "rights",
        ],
        "text": (
            "Copyright (c) {year} {holder}. All rights reserved.\n"
            "\n"
            "This software and its design, documentation and source "
            "code are\n"
            "the proprietary and confidential property of the copyright "
            "holder\n"
            "and are protected by copyright, trade-secret and other "
            "laws.\n"
            "\n"
            "No part of this work may be reproduced, distributed, "
            "transmitted,\n"
            "modified, or used to prepare derivative works, in any form "
            "or by any\n"
            "means, without the prior written permission of the "
            "copyright\n"
            "holder, except that a copy may be stored and run solely "
            "for the\n"
            "internal purposes of a licensee bound by written agreement "
            "with the\n"
            "holder.\n"
            "\n"
            "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY "
            "KIND,\n"
            "EXPRESS OR IMPLIED. IN NO EVENT SHALL THE HOLDER BE LIABLE "
            "FOR ANY\n"
            "CLAIM, DAMAGES OR OTHER LIABILITY ARISING FROM, OUT OF OR "
            "IN\n"
            "CONNECTION WITH THE SOFTWARE OR ITS USE.\n"
        ),
    },
    "mit": {
        "name": "MIT License",
        "kind": "permissive",
        "obligations": [
            "keep the copyright notice and this permission notice in "
            "all copies or substantial portions",
            "no trademark grant",
            "warranty disclaimer and liability cap travel with the code",
        ],
        "text": (
            "MIT License\n"
            "\n"
            "Copyright (c) {year} {holder}\n"
            "\n"
            "Permission is hereby granted, free of charge, to any "
            "person obtaining a copy\n"
            "of this software and associated documentation files (the "
            "\"Software\"), to\n"
            "deal in the Software without restriction, including "
            "without limitation the\n"
            "rights to use, copy, modify, merge, publish, distribute, "
            "sublicense, and/or\n"
            "sell copies of the Software, and to permit persons to whom "
            "the Software\n"
            "is furnished to do so, subject to the following "
            "conditions:\n"
            "\n"
            "The above copyright notice and this permission notice shall "
            "be included\n"
            "in all copies or substantial portions of the Software.\n"
            "\n"
            "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY "
            "KIND,\n"
            "EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE "
            "WARRANTIES OF\n"
            "MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND "
            "NONINFRINGEMENT.\n"
            "IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE "
            "LIABLE FOR ANY\n"
            "CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF "
            "CONTRACT,\n"
            "TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION "
            "WITH THE\n"
            "SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.\n"
        ),
    },
    "bsd-3-clause": {
        "name": "BSD 3-Clause \"New\" or \"Revised\" License",
        "kind": "permissive",
        "obligations": [
            "reproduce the copyright notice in source distributions",
            "reproduce the notice in documentation if provided "
            "therein",
            "no use of holder names to endorse derived products without "
            "permission",
            "no warranty",
        ],
        "text": (
            "BSD 3-Clause License\n"
            "\n"
            "Copyright (c) {year} {holder}.\n"
            "All rights reserved.\n"
            "\n"
            "Redistribution and use in source and binary forms, with or "
            "without\n"
            "modification, are permitted provided that the following "
            "conditions are met:\n"
            "\n"
            "1. Redistributions of source code must retain the above "
            "copyright notice,\n"
            "   this list of conditions and the following disclaimer.\n"
            "\n"
            "2. Redistributions in binary form must reproduce the above "
            "copyright\n"
            "   notice, this list of conditions and the following "
            "disclaimer in the\n"
            "   documentation and/or other materials provided with the "
            "distribution.\n"
            "\n"
            "3. Neither the name of the copyright holder nor the names "
            "of its\n"
            "   contributors may be used to endorse or promote products "
            "derived from\n"
            "   this software without specific prior written "
            "permission.\n"
            "\n"
            "THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND "
            "CONTRIBUTORS\n"
            "\"AS IS\" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, "
            "BUT NOT\n"
            "LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND "
            "FITNESS FOR\n"
            "A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE "
            "COPYRIGHT\n"
            "HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, "
            "INCIDENTAL,\n"
            "SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, "
            "BUT NOT LIMITED\n"
            "TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF "
            "USE, DATA, OR\n"
            "PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON "
            "ANY THEORY OF\n"
            "LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT "
            "(INCLUDING\n"
            "NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE "
            "OF THIS\n"
            "SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH "
            "DAMAGE.\n"
        ),
    },
    "isc": {
        "name": "ISC License",
        "kind": "permissive",
        "obligations": [
            "keep the copyright notice and permission notice with the "
            "code",
            "no trademark grant, no warranty",
        ],
        "text": (
            "ISC License\n"
            "\n"
            "Copyright (c) {year} {holder}\n"
            "\n"
            "Permission to use, copy, modify, and/or distribute this "
            "software for any\n"
            "purpose with or without fee is hereby granted, provided "
            "that the above\n"
            "copyright notice and this permission notice appear in all "
            "copies.\n"
            "\n"
            "THE SOFTWARE IS PROVIDED \"AS IS\" AND THE AUTHOR DISCLAIMS "
            "ALL WARRANTIES\n"
            "WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED "
            "WARRANTIES OF\n"
            "MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR "
            "BE LIABLE FOR\n"
            "ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR "
            "ANY DAMAGES\n"
            "WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, "
            "WHETHER IN AN\n"
            "ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, "
            "ARISING OUT OF\n"
            "OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS "
            "SOFTWARE.\n"
        ),
    },
    "apache-2.0": {
        "name": "Apache License 2.0",
        "kind": "permissive",
        "obligations": [
            "give recipients a copy of the license",
            "keep all copyright, patent, trademark and attribution "
            "notices",
            "attach NOTICE file contents when a NOTICE file exists",
            "state significant changes made to modified files",
            "explicit patent grant with termination on litigation",
        ],
        "text": (
            "                                 Apache License\n"
            "                           Version 2.0, January 2004\n"
            "                        http://www.apache.org/licenses/\n"
            "\n"
            "   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND "
            "DISTRIBUTION\n"
            "\n"
            "   1. Definitions.\n"
            "\n"
            "      \"License\" shall mean the terms and conditions for "
            "use, reproduction,\n"
            "      and distribution as defined by Sections 1 through 9 "
            "of this document.\n"
            "\n"
            "      \"Licensor\" shall mean the copyright owner or entity "
            "authorized by\n"
            "      the copyright owner that is granting the License.\n"
            "\n"
            "      \"Legal Entity\" shall mean the union of the acting "
            "entity and all\n"
            "      other entities that control, are controlled by, or "
            "are under common\n"
            "      control with that entity. For the purposes of this "
            "definition,\n"
            "      \"control\" means (i) the power, direct or indirect, "
            "to cause the\n"
            "      direction or management of such entity, whether by "
            "contract or\n"
            "      otherwise, or (ii) ownership of fifty percent (50%) "
            "or more of the\n"
            "      outstanding shares, or (iii) beneficial ownership of "
            "such entity.\n"
            "\n"
            "      \"You\" (or \"Your\") shall mean an individual or "
            "Legal Entity\n"
            "      exercising permissions granted by this License.\n"
            "\n"
            "      \"Source\" form shall mean the preferred form for "
            "making modifications,\n"
            "      including but not limited to software source code, "
            "documentation\n"
            "      source, and configuration files.\n"
            "\n"
            "      \"Object\" form shall mean any form resulting from "
            "mechanical\n"
            "      transformation or translation of a Source form, "
            "including but\n"
            "      not limited to compiled object code, generated "
            "documentation,\n"
            "      and conversions to other media types.\n"
            "\n"
            "      \"Work\" shall mean the work of authorship, whether "
            "in Source or\n"
            "      Object form, made available under the License, as "
            "indicated by a\n"
            "      copyright notice that is included in or attached to "
            "the work\n"
            "      (an example is provided in the Appendix below).\n"
            "\n"
            "      \"Derivative Works\" shall mean any work, whether in "
            "Source or Object\n"
            "      form, that is based on (or derived from) the Work and "
            "for which the\n"
            "      editorial revisions, annotations, elaborations, or "
            "other modifications\n"
            "      represent, as a whole, an original work of "
            "authorship. For the purposes\n"
            "      of this License, Derivative Works shall not include "
            "works that remain\n"
            "      separable from, or merely link (or bind by name) to "
            "the interfaces of,\n"
            "      the Work and Derivative Works thereof.\n"
            "\n"
            "      \"Contribution\" shall mean any work of authorship, "
            "including\n"
            "      the original version of the Work and any "
            "modifications or additions\n"
            "      to that Work or Derivative Works thereof, that is "
            "intentionally\n"
            "      submitted to Licensor for inclusion in the Work by "
            "the copyright owner\n"
            "      or by an individual or Legal Entity authorized to "
            "submit on behalf of\n"
            "      the copyright owner. For the purposes of this "
            "definition, \"submitted\"\n"
            "      means any form of electronic, verbal, or written "
            "communication sent\n"
            "      to the Licensor or its representatives, including but "
            "not limited to\n"
            "      communication on electronic mailing lists, source "
            "code control systems,\n"
            "      and issue tracking systems that are managed by, or on "
            "behalf of, the\n"
            "      Licensor for the purpose of discussing and improving "
            "the Work, but\n"
            "      excluding communication that is conspicuously marked "
            "or otherwise\n"
            "      designated in writing by the copyright owner as \"Not "
            "a Contribution.\"\n"
            "\n"
            "      \"Contributor\" shall mean Licensor and any "
            "individual or Legal Entity\n"
            "      on behalf of whom a Contribution has been received by "
            "Licensor and\n"
            "      subsequently incorporated within the Work.\n"
            "\n"
            "   2. Grant of Copyright License. Subject to the terms and "
            "conditions of\n"
            "      this License, each Contributor hereby grants to You "
            "a perpetual,\n"
            "      worldwide, non-exclusive, no-charge, royalty-free, "
            "irrevocable\n"
            "      copyright license to reproduce, prepare Derivative "
            "Works of,\n"
            "      publicly display, publicly perform, sublicense, and "
            "distribute the\n"
            "      Work and such Derivative Works in Source or Object "
            "form.\n"
            "\n"
            "   3. Grant of Patent License. Subject to the terms and "
            "conditions of\n"
            "      this License, each Contributor hereby grants to You "
            "a perpetual,\n"
            "      worldwide, non-exclusive, no-charge, royalty-free, "
            "irrevocable\n"
            "      (except as stated in this section) patent license to "
            "make, have made,\n"
            "      use, offer to sell, sell, import, and otherwise "
            "transfer the Work,\n"
            "      where such license applies only to those patent "
            "claims licensable\n"
            "      by such Contributor that are necessarily infringed by "
            "their\n"
            "      Contribution(s) alone or by combination of their "
            "Contribution(s)\n"
            "      with the Work to which such Contribution(s) was "
            "submitted. If You\n"
            "      institute patent litigation against any entity "
            "(including a\n"
            "      cross-claim or counterclaim in a lawsuit) alleging "
            "that the Work\n"
            "      or a Contribution incorporated within the Work "
            "constitutes direct\n"
            "      or contributory patent infringement, then any patent "
            "licenses\n"
            "      granted to You under this License for that Work shall "
            "terminate\n"
            "      as of the date such litigation is filed.\n"
            "\n"
            "   4. Redistribution. You may reproduce and distribute "
            "copies of the\n"
            "      Work or Derivative Works thereof in any medium, with "
            "or without\n"
            "      modifications, and in Source or Object form, "
            "provided that You\n"
            "      meet the following conditions:\n"
            "\n"
            "      (a) You must give any other recipients of the Work or "
            "Derivative\n"
            "          Works a copy of this License; and\n"
            "\n"
            "      (b) You must cause any modified files to carry "
            "prominent notices\n"
            "          stating that You changed the files; and\n"
            "\n"
            "      (c) You must retain, in the Source form of any "
            "Derivative Works\n"
            "          that You distribute, all copyright, patent, "
            "trademark, and\n"
            "          attribution notices from the Source form of the "
            "Work,\n"
            "          excluding those notices that do not pertain to "
            "any part of\n"
            "          the Derivative Works; and\n"
            "\n"
            "      (d) If the Work includes a \"NOTICE\" text file as "
            "part of its\n"
            "          distribution, then any Derivative Works that You "
            "distribute must\n"
            "          include a readable copy of the attribution "
            "notices contained\n"
            "          within such NOTICE file, excluding those notices "
            "that do not\n"
            "          pertain to any part of the Derivative Works, in "
            "at least one\n"
            "          of the following places: within a NOTICE text "
            "file distributed\n"
            "          as part of the Derivative Works; within the "
            "Source form or\n"
            "          documentation, if provided along with the "
            "Derivative Works; or,\n"
            "          within a display generated by the Derivative "
            "Works, if and\n"
            "          wherever such third-party notices normally "
            "appear. The contents\n"
            "          of the NOTICE file are for informational purposes "
            "only and\n"
            "          do not modify the License. You may add Your own "
            "attribution\n"
            "          notices within Derivative Works that You "
            "distribute, alongside\n"
            "          or as an addendum to the NOTICE text from the "
            "Work, provided\n"
            "          that such additional attribution notices cannot "
            "be construed\n"
            "          as modifying the License.\n"
            "\n"
            "      You may add Your own copyright statement to Your "
            "modifications and\n"
            "      may provide additional or different license terms "
            "and conditions\n"
            "      for use, reproduction, or distribution of Your "
            "modifications, or\n"
            "      for any such Derivative Works as a whole, provided "
            "Your use,\n"
            "      reproduction, and distribution of the Work otherwise "
            "complies with\n"
            "      the conditions stated in this License.\n"
            "\n"
            "   5. Submission of Contributions. Unless You explicitly "
            "state otherwise,\n"
            "      any Contribution intentionally submitted for "
            "inclusion in the Work\n"
            "      by You to the Licensor shall be under the terms and "
            "conditions of\n"
            "      this License, without any additional terms or "
            "conditions.\n"
            "      Notwithstanding the above, nothing herein shall "
            "supersede or modify\n"
            "      the terms of any separate license agreement you may "
            "have executed\n"
            "      with Licensor regarding such Contributions.\n"
            "\n"
            "   6. Trademarks. This License does not grant permission "
            "to use the trade\n"
            "      names, trademarks, service marks, or product names "
            "of the Licensor,\n"
            "      except as required for reasonable and customary use "
            "in describing the\n"
            "      origin of the Work and reproducing the content of "
            "the NOTICE file.\n"
            "\n"
            "   7. Disclaimer of Warranty. Unless required by applicable "
            "law or\n"
            "      agreed to in writing, Licensor provides the Work (and "
            "each\n"
            "      Contributor provides its Contributions) on an \"AS "
            "IS\" BASIS,\n"
            "      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either "
            "express or\n"
            "      implied, including, without limitation, any "
            "warranties or conditions\n"
            "      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or "
            "FITNESS FOR A\n"
            "      PARTICULAR PURPOSE. You are solely responsible for "
            "determining the\n"
            "      appropriateness of using or redistributing the Work "
            "and assume any\n"
            "      risks associated with Your exercise of permissions "
            "under this License.\n"
            "\n"
            "   8. Limitation of Liability. In no event and under no "
            "legal theory,\n"
            "      whether in tort (including negligence), contract, or "
            "otherwise,\n"
            "      unless required by applicable law (such as deliberate "
            "and grossly\n"
            "      negligent acts) or agreed to in writing, shall any "
            "Contributor be\n"
            "      liable to You for damages, including any direct, "
            "indirect, special,\n"
            "      incidental, or consequential damages of any character "
            "arising as a\n"
            "      result of this License or out of the use or inability "
            "to use the\n"
            "      Work (including but not limited to damages for loss "
            "of goodwill,\n"
            "      work stoppage, computer failure or malfunction, or "
            "any and all\n"
            "      other commercial damages or losses), even if such "
            "Contributor\n"
            "      has been advised of the possibility of such damages.\n"
            "\n"
            "   9. Accepting Warranty or Additional Liability. While "
            "redistributing\n"
            "      the Work or Derivative Works thereof, You may choose "
            "to offer,\n"
            "      and charge a fee for, acceptance of support, "
            "warranty, indemnity,\n"
            "      or other liability obligations and/or rights "
            "consistent with this\n"
            "      License. However, in accepting such obligations, You "
            "may act only\n"
            "      on Your own behalf and on Your sole responsibility, "
            "not on behalf\n"
            "      of any other Contributor, and only if You agree to "
            "indemnify,\n"
            "      defend, and hold each Contributor harmless for any "
            "liability\n"
            "      incurred by, or claims asserted against, such "
            "Contributor by reason\n"
            "      of your accepting any such warranty or additional "
            "liability.\n"
            "\n"
            "   END OF TERMS AND CONDITIONS\n"
            "\n"
            "   APPENDIX: How to apply the Apache License to your work.\n"
            "\n"
            "      To apply the Apache License to your work, attach the "
            "following\n"
            "      boilerplate notice, with the fields enclosed by "
            "brackets \"[]\"\n"
            "      replaced with your own identifying information. "
            "(Don't include\n"
            "      the brackets!)  The text should be enclosed in the "
            "appropriate\n"
            "      comment syntax for the file format. We also recommend "
            "that a\n"
            "      file or class name and description of purpose be "
            "included on the\n"
            "      same \"printed page\" as the copyright notice for "
            "easier\n"
            "      identification within third-party archives.\n"
            "\n"
            "   Copyright [yyyy] [name of copyright owner]\n"
            "\n"
            "   Licensed under the Apache License, Version 2.0 (the "
            "\"License\");\n"
            "   you may not use this file except in compliance with the "
            "License.\n"
            "   You may obtain a copy of the License at\n"
            "\n"
            "       http://www.apache.org/licenses/LICENSE-2.0\n"
            "\n"
            "   Unless required by applicable law or agreed to in "
            "writing, software\n"
            "   distributed under the License is distributed on an \"AS "
            "IS\" BASIS,\n"
            "   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either "
            "express or implied.\n"
            "   See the License for the specific language governing "
            "permissions and\n"
            "   limitations under the License.\n"
        ),
    },
    "cc-by-4.0": {
        "name": "Creative Commons Attribution 4.0 International",
        "kind": "permissive",
        "obligations": [
            "attribute the licensor, link the license, indicate changes",
            "no additional restrictions may be applied to licensed "
            "material",
        ],
        # full text ships from upstream; HEBE drafts the notice
        "text": None,
        "notice": (
            "{title} (c) {year} by {holder} is licensed under CC BY 4.0."
            " To view a copy of this license, visit"
            " https://creativecommons.org/licenses/by/4.0\n"
        ),
    },
    "gpl-3.0-only": {
        "name": "GNU General Public License v3.0 only",
        "kind": "copyleft",
        "obligations": [
            "license derivative works under GPL-3.0-only",
            "provide complete corresponding source to recipients",
            "keep notices intact; state changes to modified files",
            "apply the official canonical text verbatim from gnu.org",
        ],
        "text": None,
        "source": "https://www.gnu.org/licenses/gpl-3.0.txt",
    },
}

# ------------------------------------------------------- knowledge base
KNOWLEDGE = {
    "copyright": [
        "Berne Convention: original works are protected automatically "
        "from the moment of fixation in a tangible medium - registration "
        "is optional in most signatory states (US registration adds "
        "statutory-damages eligibility).",
        "Copyright covers expression (source code, docs, art), never "
        "ideas, algorithms or facts; those need patents (ideas) or "
        "trade-secret discipline (facts).",
        "Notice format: 'Copyright (c) YEAR HOLDER. All rights "
        "reserved.' - not legally required in Berne states, but it "
        "defeats innocent-infringement defenses and enables statutory "
        "damages.",
        "Works made for hire / employee creations default to the "
        "employer in the US; contractors own their work absent a signed "
        "assignment - always paper contractor agreements.",
        "Joint authorship requires intent of merged contributions; "
        "each joint author may license the whole non-exclusively, so "
        "agree revenue shares in writing up front.",
    ],
    "licenses": [
        "Permissive (MIT/BSD/ISC/Apache-2.0): minimal obligations, "
        "closed-source derivatives allowed; Apache-2.0 adds an express "
        "patent grant with a retaliation clause.",
        "Copyleft (GPL-3.0): derivatives must carry the same license "
        "and ship source; strong reciprocal duty - keep it away from "
        "proprietary code paths.",
        "CC licenses target creative/media works, NOT code (CC-BY-4.0 "
        "is fine for documentation and design assets).",
        "License compatibility flows one way: MIT/BSD code can enter "
        "an Apache/GPL project; GPL code cannot enter a permissive or "
        "proprietary project.",
        "Choosing a license is irrevocable for already-released copies; "
        "dual-licensing requires owning 100% of contributions (CLA).",
        "This workspace currently defaults to proprietary/all-rights-"
        "reserved until the operator declares an open-source license "
        "(platform goal per DESIGN.md).",
    ],
    "notice": [
        "Every shipped artifact should carry: title, copyright line, "
        "license identifier (SPDX), and a warranty disclaimer.",
        "SPDX identifiers (MIT, Apache-2.0, GPL-3.0-only...) make "
        "license scans machine-checkable - add them to headers and "
        "package manifests.",
        "Third-party bundles need a NOTICE/attribution file listing "
        "every embedded component, its license and upstream source.",
    ],
    "trade-secret": [
        "A trade secret is information with economic value FROM being "
        "secret, protected by reasonable measures (DTSA/EU Directive "
        "2016/943).",
        "Reasonable measures: access control, classification labels, "
        "NDAs, exit interviews, logging - exactly what this fleet's "
        "classification + ledger machinery provides.",
        "Public disclosure destroys protection instantly and forever; "
        "publishing DESIGN.md as open source surrenders trade-secret "
        "status for what it contains.",
        "Mark confidential material 'Confidential' (or Restricted) and "
        "restrict circulation; courts look for those labels.",
    ],
    "nda": [
        "A workable NDA defines: parties, what is confidential "
        "(definition + marking rules), permitted use, term "
        "(3-5 years typical), return/destruction duty, carve-outs "
        "(independent development, public knowledge, court order).",
        "Mutual NDAs suit partnerships; one-way suits disclosure to a "
        "vendor or reviewer.",
        "Injunctive-relief clauses matter: money damages rarely fix a "
        "leak.",
    ],
    "open-sourcing": [
        "Checklist before flipping the platform public: (1) operator "
        "decision recorded here, (2) LICENSE chosen and applied at "
        "root, (3) secret sweep green (verify_secrets.py), (4) "
        "third-party NOTICE complete, (5) retired-scope guard green "
        "(verify_scope.py), (6) classified records re-reviewed.",
        "Once public, keep provenance seals (Hades) so authenticity "
        "can be proven against forks.",
        "CLA or DCO decides whether the project can ever re-license "
        "or accept broad contributions.",
    ],
    "trademark": [
        "Trademarks protect source identifiers (names/logos) in "
        "commerce - rights arise from USE, strongest when registered "
        "in relevant classes.",
        "The rebrand exists precisely to keep retired public marks out "
        "of this tree; verify_scope.py enforces the boundary "
        "mechanically.",
        "Use marks as adjectives with a generic noun, notice symbol "
        "on first prominent use, and never accept genericide.",
    ],
    "dmca": [
        "Takedown recipe (host/platform): identify the infringed work, "
        "the infringing URL, good-faith statement, authority statement, "
        "signature - send to the registered DMCA agent; counter-notices "
        "restore content after 10-14 business days unless suit is "
        "filed.",
        "As a host, register an agent with the US Copyright Office and "
        "run a repeat-infringer policy to keep safe-harbor protection.",
    ],
}


def knowledge_topics():
    """Sorted topic names available to `advise`."""
    return sorted(KNOWLEDGE)


def license_text(spdx, year="", holder="", title=""):
    """Render a license body with the house variables filled in."""
    entry = LICENSES.get(spdx)
    if not entry:
        raise KeyError("unknown spdx: %r (have: %s)"
                       % (spdx, ", ".join(sorted(LICENSES))))
    if entry["text"] is not None:
        return entry["text"].format(year=year, holder=holder)
    notice = entry.get("notice")
    if notice:                                   # e.g. CC-BY-4.0 stub
        return notice.format(year=year, holder=holder,
                             title=title or "(workspace)")
    return ("Apply the canonical text verbatim from %s\n"
            % entry.get("source", "the official source"))
