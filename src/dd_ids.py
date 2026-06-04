"""
DD-IDS: Data-Driven Intrusion Detection System
PCA with Hotelling T² and Q (SPE) statistics

Reference:
    Masood et al., "A Blockchain-Based Data-Driven Fault-Tolerant Control System
    for Smart Factories in Industry 4.0", Computer Communications, vol. 204, 2023.
    https://doi.org/10.1016/j.comcom.2023.02.015

Applied to the Tennessee Eastman Process (TEP) — a standard ICS security benchmark.
Detects False Data Injection attacks (bias and static) on sensor measurements.
"""

import numpy as np
from scipy import stats


class DDIDS:
    """
    Data-Driven Intrusion Detection System using PCA.

    Detects anomalous sensor behaviour using Hotelling's T² and Q statistics.
    Trained on clean (attack-free) process data. Applied online at each sample.

    Parameters
    ----------
    variance_threshold : float
        Percentage of total variance to retain (default 0.90 = 90%).
        Controls the number of principal components c selected.
    significance_level : float
        α for computing J_T² and J_Q thresholds (default 0.01 = 99% confidence).
    """

    def __init__(self, variance_threshold: float = 0.90, significance_level: float = 0.01):
        self.variance_threshold = variance_threshold
        self.significance_level = significance_level

        # Set during fit()
        self.V_pc = None        # Principal component eigenvectors (w × c)
        self.V_res = None       # Residual eigenvectors (w × w-c)
        self.Lambda_pc = None   # Principal eigenvalues (c × c diagonal)
        self.J_T2 = None        # Hotelling T² detection threshold
        self.J_Q = None         # Q (SPE) detection threshold
        self.c = None           # Number of principal components selected
        self.N = None           # Training samples
        self.w = None           # Process variables
        self.mean_ = None       # Training mean (for normalisation)
        self.std_ = None        # Training std (for normalisation)

    def fit(self, Z_train: np.ndarray) -> "DDIDS":
        """
        Train the PCA model on clean (attack-free) process data.

        Parameters
        ----------
        Z_train : np.ndarray of shape (N, w)
            Training dataset: N samples, w process variables.
            Should be collected under normal operating conditions.

        Returns
        -------
        self
        """
        self.N, self.w = Z_train.shape

        # Step 1: Normalise to zero mean, unit variance
        self.mean_ = Z_train.mean(axis=0)
        self.std_ = Z_train.std(axis=0, ddof=1)
        self.std_[self.std_ == 0] = 1  # Avoid division by zero
        Z = (Z_train - self.mean_) / self.std_

        # Step 2: Eigenvalue decomposition of covariance matrix
        S = (1 / (self.N - 1)) * Z.T @ Z
        eigenvalues, eigenvectors = np.linalg.eigh(S)

        # Sort descending (eigh returns ascending)
        idx = np.argsort(eigenvalues)[::-1]
        eigenvalues = eigenvalues[idx]
        eigenvectors = eigenvectors[:, idx]

        # Step 3: Select c components explaining >= variance_threshold of total variance
        cumulative_variance = np.cumsum(eigenvalues) / eigenvalues.sum()
        self.c = int(np.searchsorted(cumulative_variance, self.variance_threshold)) + 1
        self.c = max(1, min(self.c, self.w - 1))

        # Step 4: Partition eigenvectors and eigenvalues
        self.V_pc = eigenvectors[:, :self.c]          # w × c
        self.V_res = eigenvectors[:, self.c:]          # w × (w-c)
        self.Lambda_pc = np.diag(eigenvalues[:self.c]) # c × c

        # Step 5: Compute detection thresholds
        self.J_T2 = self._compute_T2_threshold()
        self.J_Q = self._compute_Q_threshold(eigenvalues)

        return self

    def _compute_T2_threshold(self) -> float:
        """Hotelling T² threshold using F-distribution."""
        alpha = self.significance_level
        c, N = self.c, self.N
        F_critical = stats.f.ppf(1 - alpha, c, N - c)
        return (c * (N**2 - 1)) / (N * (N - c)) * F_critical

    def _compute_Q_threshold(self, eigenvalues: np.ndarray) -> float:
        """Q (SPE) threshold — Jackson-Mudholkar approximation."""
        alpha = self.significance_level
        theta = [sum(eigenvalues[self.c:] ** i) for i in [1, 2, 3]]
        h0 = 1 - (2 * theta[0] * theta[2]) / (3 * theta[1] ** 2)
        c_alpha = stats.norm.ppf(1 - alpha)
        term1 = c_alpha * np.sqrt(2 * theta[1] * h0 ** 2) / theta[0]
        term2 = theta[1] * h0 * (h0 - 1) / (theta[0] ** 2)
        return theta[0] * (term1 + 1 + term2) ** (1 / h0)

    def detect(self, z_k: np.ndarray) -> dict:
        """
        Run online detection on a single new sample.

        Parameters
        ----------
        z_k : np.ndarray of shape (w,)
            New process measurement vector.

        Returns
        -------
        dict with keys:
            T2 : float       — Hotelling T² statistic
            Q  : float       — Q (SPE) statistic
            I  : int         — Detection flag (1 = attack detected, 0 = normal)
            J_T2 : float     — T² threshold
            J_Q  : float     — Q threshold
        """
        if self.V_pc is None:
            raise RuntimeError("Call fit() before detect().")

        # Normalise the sample
        z = (z_k - self.mean_) / self.std_

        # Compute T² statistic
        T2 = float(z @ self.V_pc @ np.linalg.inv(self.Lambda_pc) @ self.V_pc.T @ z)

        # Compute Q statistic
        Q = float(z @ self.V_res @ self.V_res.T @ z)

        # Detection flag: attack if BOTH thresholds exceeded
        I = int(T2 > self.J_T2 and Q > self.J_Q)

        return {"T2": T2, "Q": Q, "I": I, "J_T2": self.J_T2, "J_Q": self.J_Q}

    def detect_batch(self, Z: np.ndarray) -> dict:
        """
        Run detection on a batch of samples.

        Parameters
        ----------
        Z : np.ndarray of shape (N, w)

        Returns
        -------
        dict with arrays T2, Q, I for each sample.
        """
        results = [self.detect(Z[k]) for k in range(len(Z))]
        return {
            "T2": np.array([r["T2"] for r in results]),
            "Q":  np.array([r["Q"] for r in results]),
            "I":  np.array([r["I"] for r in results]),
        }


class SensorIdentifier:
    """
    Identifies which sensor has been compromised using residual analysis.

    Compares measured sensor values against NNARX observer predictions.
    A sensor is flagged as compromised when ||r_{i,k}|| > ε_i.

    The residual threshold ε_i is computed from clean data as:
        ε_i = sup ||r_{i,k}||  (k over clean training period)
    """

    def __init__(self):
        self.epsilon = None     # Residual thresholds per sensor
        self.n_sensors = None

    def fit(self, residuals_clean: np.ndarray) -> "SensorIdentifier":
        """
        Compute residual thresholds from clean (attack-free) residuals.

        Parameters
        ----------
        residuals_clean : np.ndarray of shape (N, n_sensors)
            Residuals r_{i,k} = y_{i,k} - ŷ_{i,k} during clean operation.
        """
        self.n_sensors = residuals_clean.shape[1]
        self.epsilon = np.max(np.abs(residuals_clean), axis=0)
        return self

    def identify(self, y_k: np.ndarray, y_hat_k: np.ndarray) -> dict:
        """
        Identify compromised sensors.

        Parameters
        ----------
        y_k     : np.ndarray — measured sensor values
        y_hat_k : np.ndarray — predicted values from NNARX observer

        Returns
        -------
        dict with:
            residuals : np.ndarray — r_{i,k} for each sensor
            Q_flags   : np.ndarray — 1 if sensor i is compromised, 0 otherwise
            compromised : list     — indices of compromised sensors
        """
        residuals = y_k - y_hat_k
        norms = np.abs(residuals)
        Q_flags = (norms > self.epsilon).astype(int)
        compromised = list(np.where(Q_flags == 1)[0])

        return {
            "residuals": residuals,
            "Q_flags": Q_flags,
            "compromised": compromised,
        }


class Reconfigurer:
    """
    Reconfigures sensor measurements during an attack.

    Replaces compromised sensor readings with observer predictions,
    corrected by the residual:
        y_{i,k} ≈ ỹ_{i,k} − r_{i,k} · m_{i,k}

    m_{i,k} = 1 while sensor is flagged as compromised, 0 otherwise.
    """

    def reconfigure(
        self,
        y_k: np.ndarray,
        y_hat_k: np.ndarray,
        residuals: np.ndarray,
        Q_flags: np.ndarray,
    ) -> np.ndarray:
        """
        Compute true sensor measurements.

        Parameters
        ----------
        y_k       : measured (potentially corrupted) values
        y_hat_k   : observer predictions
        residuals : r_{i,k} = y_{i,k} - ŷ_{i,k}
        Q_flags   : 1 for compromised sensors

        Returns
        -------
        y_true : np.ndarray — reconfigured measurements for all sensors
        """
        y_true = y_k.copy()
        for i, flag in enumerate(Q_flags):
            if flag == 1:
                # Reconfigured measurement: observer prediction corrected by residual
                y_true[i] = y_k[i] - residuals[i] * flag
        return y_true
