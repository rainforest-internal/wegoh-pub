"""Bounded personal L2 logistic model of explicitly labelled public course features."""
import math

MODEL_VERSION='personal-logistic-v1'
DIMENSIONS=3
MAX_SAMPLES=200

def sigmoid(z):
    if z>=0:
        e=math.exp(-z)
        return 1/(1+e)
    e=math.exp(z)
    return e/(1+e)

def fit(samples):
    # Caller must first enforce current owner consent/epoch and exact approval.
    # A sample is server-derived public x and explicit y, not client input.
    if len(samples)>MAX_SAMPLES:
        raise ValueError('Bounded sample limit')
    for x,y in samples:
        if len(x)!=DIMENSIONS or type(y)is not int or y not in(0,1):
            raise ValueError('Invalid sample')
        if any(type(v)not in(int,float)or not -1<=v<=1 or not math.isfinite(v)for v in x):
            raise ValueError('Invalid public feature')
    ready=len(samples)>=4 and {y for _,y in samples}=={0,1} and len({tuple(x)for x,_ in samples})>=2
    if not ready:
        return dict(version=MODEL_VERSION,status='collecting-feedback',weights=None)
    weights=[0.0]*DIMENSIONS
    for _ in range(80):
        gradient=[0.5*w for w in weights]
        for x,y in samples:
            error=sigmoid(sum(w*v for w,v in zip(weights,x)))-y
            for j in range(DIMENSIONS):gradient[j]+=error*x[j]/len(samples)
        weights=[w-0.1*g for w,g in zip(weights,gradient)]
    if not all(math.isfinite(w)for w in weights):
        raise ValueError('Model unavailable')
    return dict(version=MODEL_VERSION,status='trained',weights=weights)

def score(model,public_features):
    if model['version']!=MODEL_VERSION or model['status']!='trained':
        raise ValueError('No eligible trained model')
    if len(public_features)!=DIMENSIONS or len(model['weights'])!=DIMENSIONS:
        raise ValueError('Invalid model dimensions')
    if any(type(v)not in(int,float)or not -1<=v<=1 or not math.isfinite(v)for v in public_features):
        raise ValueError('Invalid public feature')
    if any(type(w)not in(int,float)or not -100<=w<=100 or not math.isfinite(w)for w in model['weights']):
        raise ValueError('Invalid model weights')
    # Current eligibility fingerprint and consent must be rechecked by caller.
    return sigmoid(sum(w*x for w,x in zip(model['weights'],public_features)))
