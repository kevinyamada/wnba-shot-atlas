"""Independent synthetic mathematical checks; no extra basketball data."""
from pathlib import Path
import json
import math
import numpy as np
from scipy.special import expit


def main():
    # Compare the implemented spectral approximation against the closed-form
    # anisotropic Matérn-5/2 covariance at fixed court locations.
    points=np.array([[0,0],[2,0],[10,5],[20,-10],[35,20],[-5,-25]],float)
    ell=np.array([8.,8.]);r=np.linalg.norm((points[:,None]-points[None,:])/ell,axis=2)
    exact=(1+np.sqrt(5)*r+5*r*r/3)*np.exp(-np.sqrt(5)*r)
    rows=[]
    for basis in [24,32,40,64]:
        for domain in [[36.,38.],[48.,50.]]:
            L=np.array(domain);modes=np.array([(i,j) for i in range(1,basis+1) for j in range(1,basis+1)])
            omega=np.pi*modes/(2*L)
            phi=np.prod(np.sin((points[:,None,:]-[18.,0.]+L)*omega)/np.sqrt(L),axis=2)
            psd=4*np.pi*math.gamma(3.5)*5**2.5/math.gamma(2.5)*ell.prod()/(5+np.sum((omega*ell)**2,axis=1))**3.5
            cov=(phi*psd)@phi.T
            assert np.linalg.eigvalsh(cov).min()>0 and np.isfinite(cov).all()
            rows.append({'basis_per_axis':basis,'domain_half_widths':domain,'maximum_covariance_error':float(abs(cov-exact).max()),'mean_covariance_error':float(abs(cov-exact).mean()),'minimum_prior_variance':float(np.diag(cov).min()),'maximum_prior_variance':float(np.diag(cov).max())})
    # Zero-sum effects have the requested marginal variance and are correlated.
    rng=np.random.default_rng(20261115);z=rng.normal(size=(100000,100));a=(z-z.mean(axis=1,keepdims=True))*np.sqrt(100/99)
    assert abs(a.sum(axis=1)).max()<1e-12 and np.allclose(a.var(axis=0),1,atol=.02)
    latent=np.array([-2.,0.,3.]);assert abs(expit(latent).mean()-expit(latent.mean()))>.02
    report={'synthetic_only':True,'spectral_checks':rows,'finite_positive_covariances':True,'zero_sum_player_marginal_variance_check':True,
            'posterior_transform_check':'Average probabilities after inverse-logit; inverse-logit of average logits is different.',
            'approximation_limit':'A finite Dirichlet-domain basis is not the exact stationary GP. Errors here use length 8 ft only; basis/domain/length sensitivity is evaluated on the real Data1 benchmark.'}
    out=Path(__file__).resolve().parent/'results/data1/numerical_checks.json';out.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
