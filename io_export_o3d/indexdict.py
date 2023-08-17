"""IndexDict Module

This module provides a class that maps an ordered set of keys to their
indexes—retrieving the value of a key returns the index of that key,
with unseen keys being appended.

Classes:
`IndexDict`: Maps an ordered set of keys to their indexes.


Copyright 2023 Nathan Burnham

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

# <pep8-80 compliant>


class IndexDict(dict):
    """
    A dictionary that maps an ordered set of keys to their indexes.

    Retrieving the value of a key from an IndexDict returns the index of
    that key, with unseen keys being appended. NO ATTEMPT IS MADE TO
    PREVENT INVALIDATION BY REMOVING OR SETTING THE VALUE OF KEYS.
    """

    def __missing__(self, k) -> int:
        self[k] = len(self)
        return self[k]
