import json
import numpy as np

sd = json.load(open('./constants/stardust.json', 'r'))
sd = {int(k): v for k, v in sd.items()}
cp = json.load(open('./constants/cpmultiplier.json', 'r'))
cp = {float(k): v for k, v in cp.items()}
bs = json.load(open('./constants/basestats_id.json', 'r'))
bs = {int(k): {kk: int(vv) for kk, vv in v.items()} for k, v in bs.items()}



def calculate_max_cp(atk_iv, def_iv, sta_iv, pokemon, cp_multiplier):
    return np.floor(0.1
                    * (bs[pokemon]['Attack'] + atk_iv) * cp_multiplier
                    * np.sqrt((bs[pokemon]['Defense'] + def_iv) * cp_multiplier)
                    * np.sqrt((bs[pokemon]['Stamina'] + sta_iv) * cp_multiplier)
                    )

def perfect(atk_iv, def_iv, sta_iv):
    return (atk_iv + def_iv + sta_iv) / 3.0
