# LotusScript-Source-Code-Count
Count source code in NSF or NTF databases


For smaller and cleaner DXL export (similar tu mime export)
  In Domino Designer go to 
  - File->Preferences->Domino Designer->Source Control
  deselect "Use Binary DXL for source control operations" - less work for our script do decode base64 stuff :)


Open .nfs or .ntf in Domino Designer then:
 - File -> Team Development -> Set Up Source Control for this Application...


cmd to this directory and run python script
python clean_and_count_lines.py c:\path\to\ODP

