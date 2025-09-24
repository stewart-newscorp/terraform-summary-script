
requires protobuf, ie. `pip install protobuf`

writes a markdown file table of changes, and logs a coloured summary to stdout

Looks under an "accounts" folder to find terraform plan files called "tfplan.out"

It logs an output like:

```text
mise exec -- pip install protobuf
mise exec -- python summary_proto.py tfplan.out
INFO:__main__:Running summary_proto.py
INFO:__main__:Reading plan file: tfplan.out
INFO:__main__:Looking for plan files in ./accounts directory
Account                                            Add        Change     Destroy   
--------------------------------------------------------------------------------
folder1/account1                            0          0          0         
folder2/account2                            0          0          0         
```
