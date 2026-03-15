import pickle

pt = pickle.load(open("pt.pkl", "rb"))

print(type(pt))
print(pt.shape)
print(pt.head())