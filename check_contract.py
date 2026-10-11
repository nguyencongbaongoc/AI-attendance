from app.data.contracts import get_model_contract
contract = get_model_contract('scrfd')
print(f'Input height: {contract.preprocessing.input_height}')
print(f'Input width: {contract.preprocessing.input_width}')
print(f'Mean: {contract.preprocessing.mean}')
print(f'Std: {contract.preprocessing.std}')
print(f'Channel order: {contract.preprocessing.channel_order}')
print(f'Dir: {[x for x in dir(contract.preprocessing) if not x.startswith("_")]}')