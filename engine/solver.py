"""A tiny modelling layer so the planner runs with two solvers.

- On a laptop: Google OR-Tools CP-SAT (fast, the one we present).
- In the browser (stlite / Pyodide, where OR-Tools cannot be installed):
  SciPy's MILP solver (HiGHS). Same model, same optimal plans.

Only what the planner needs: yes/no and integer variables, linear
constraints, implications, exactly-one, and a linear objective to maximise.
"""
from __future__ import annotations

import time

try:
    from ortools.sat.python import cp_model
    BACKEND = "OR-Tools CP-SAT"
except ImportError:  # e.g. running in the browser
    cp_model = None
    BACKEND = "SciPy MILP (HiGHS)"


class LinExpr:
    __array_ufunc__ = None  # make numpy numbers defer to our * and +

    def __init__(self, terms=None, const=0):
        self.terms = dict(terms or {})
        self.const = const

    @staticmethod
    def of(x):
        if isinstance(x, LinExpr):
            return x
        if isinstance(x, Var):
            return LinExpr({x.idx: 1})
        return LinExpr(const=x)

    def __add__(self, o):
        o = LinExpr.of(o)
        t = dict(self.terms)
        for k, v in o.terms.items():
            t[k] = t.get(k, 0) + v
        return LinExpr(t, self.const + o.const)

    __radd__ = __add__

    def __neg__(self):
        return LinExpr({k: -v for k, v in self.terms.items()}, -self.const)

    def __sub__(self, o):
        return self + (-LinExpr.of(o))

    def __rsub__(self, o):
        return LinExpr.of(o) - self

    def __mul__(self, k):
        return LinExpr({i: v * k for i, v in self.terms.items()}, self.const * k)

    __rmul__ = __mul__

    def __le__(self, o):
        return Constraint(self - o, None, 0)

    def __ge__(self, o):
        return Constraint(self - o, 0, None)

    def __eq__(self, o):
        return Constraint(self - o, 0, 0)

    __hash__ = None


class Var(LinExpr):
    def __init__(self, idx, lo, hi, name):
        super().__init__({idx: 1})
        self.idx, self.lo, self.hi, self.name = idx, lo, hi, name

    __hash__ = object.__hash__


class Constraint:
    def __init__(self, expr, lo, hi):  # lo <= expr <= hi  (None = unbounded)
        self.expr, self.lo, self.hi = expr, lo, hi


class Model:
    def __init__(self):
        self.vars, self.cons, self.obj = [], [], LinExpr()
        self._values, self.status = {}, "not solved"

    def bool_var(self, name):
        return self.int_var(0, 1, name)

    def int_var(self, lo, hi, name):
        v = Var(len(self.vars), lo, hi, name)
        self.vars.append(v)
        return v

    def add(self, c: Constraint):
        self.cons.append(c)

    def add_implication(self, a, b):  # a -> b  for yes/no variables
        self.add(a <= b)

    def add_exactly_one(self, vs):
        self.add(sum(vs) == 1)

    def maximize(self, expr):
        self.obj = LinExpr.of(expr)

    def value(self, v) -> int:
        return self._values[v.idx]

    def solve(self, time_limit_s: float = 5, workers: int = 8) -> str:
        t0 = time.time()
        self.status = self._solve_ortools(time_limit_s, workers) if cp_model else self._solve_scipy(time_limit_s)
        self.solve_s = time.time() - t0
        return self.status

    # ---------- backends ----------
    def _solve_ortools(self, limit, workers):
        m = cp_model.CpModel()
        xs = [m.NewIntVar(int(v.lo), int(v.hi), v.name) for v in self.vars]

        def expr(e):
            return sum(int(round(c)) * xs[i] for i, c in e.terms.items()) + int(round(e.const))

        for c in self.cons:
            e = expr(c.expr)
            if c.lo is not None:
                m.Add(e >= int(c.lo))
            if c.hi is not None:
                m.Add(e <= int(c.hi))
        m.Maximize(expr(self.obj))
        s = cp_model.CpSolver()
        s.parameters.max_time_in_seconds = limit
        s.parameters.num_workers = workers
        st = s.Solve(m)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return "infeasible"
        self._values = {i: s.Value(x) for i, x in enumerate(xs)}
        return "optimal" if st == cp_model.OPTIMAL else "feasible (time limit)"

    def _solve_scipy(self, limit):
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import coo_matrix

        n = len(self.vars)
        c = np.zeros(n)
        for i, v in self.obj.terms.items():
            c[i] = -v  # milp minimises
        rows, cols, vals, lb, ub = [], [], [], [], []
        for r, con in enumerate(self.cons):
            for i, v in con.expr.terms.items():
                rows.append(r); cols.append(i); vals.append(v)
            lb.append(-np.inf if con.lo is None else con.lo - con.expr.const)
            ub.append(np.inf if con.hi is None else con.hi - con.expr.const)
        A = coo_matrix((vals, (rows, cols)), shape=(len(self.cons), n)).tocsr()
        scale = max(1.0, float(np.abs(c).max()))  # keep the objective numerically tame
        res = milp(c / scale, constraints=LinearConstraint(A, lb, ub), integrality=np.ones(n),
                   bounds=Bounds([v.lo for v in self.vars], [v.hi for v in self.vars]),
                   options={"time_limit": limit, "mip_rel_gap": 1e-9})
        if res.x is None:
            return "infeasible"
        self._values = {i: int(round(x)) for i, x in enumerate(res.x)}
        return "optimal" if res.status == 0 else "feasible (time limit)"
