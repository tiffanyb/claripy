import itertools
bitvec_counter = itertools.count()

import logging
l = logging.getLogger('claripy.claripy')

class Claripy(object):
    def __init__(self, name, model_backends, solver_backends, parallel=None):
        self.name = name
        self.solver_backends = solver_backends
        self.model_backends = model_backends
        self.unique_names = True
        self.parallel = parallel if parallel else False
        self.save_ast = True

        self.true = self.BoolVal(True)
        self.false = self.BoolVal(False)

    #
    # Backend management
    #
    def backend_of_type(self, b_type):
        for b in self.model_backends + self.solver_backends:
            if type(b) is b_type:
                return b
        return None

    #
    # Solvers
    #
    def solver(self):
        '''
        Returns a new solver.
        '''
        raise NotImplementedError()

    #
    # Operations
    #

    def wrap(self, o, symbolic=False, variables=None):
        if type(o) is E:
            return o
        else:
            return E(self, o, set() if variables is None else variables, symbolic)

    def _do_op_raw(self, name, args):
        resolved = False

        if not self.save_ast:
            for b in self.model_backends:
                try:
                    if raw: r = b.call(name, args)
                    else:   r = b.call_expr(name, args)
                    resolved = True
                    break
                except BackendError:
                    continue

        if not resolved:
            # Special case for Reverse
            r = None
            if name == 'Reverse':
                arg = args[0]
                if isinstance(arg, E) and \
                        isinstance(arg._actual_model, A) and \
                        arg.ast.op == 'Reverse':
                    # Unpack it :-)
                    r = arg.ast.args[0]

            if r is None:
                r = A(self, name, args)

        return r


    def _do_op(self, name, args, variables=None, symbolic=None, raw=False, simplified=False):
        r = self._do_op_raw(name, args)

        if symbolic is None:
            symbolic = any(arg.symbolic if isinstance(arg, E) else False for arg in args)
        if variables is None:
            all_variables = ((arg.variables if isinstance(arg, E) else set()) for arg in args)
            variables = set.union(*all_variables)

        return E(self, r, variables, symbolic, simplified=simplified)

    def BitVec(self, name, size, explicit_name=None):
        explicit_name = explicit_name if explicit_name is not None else False
        if self.unique_names and not explicit_name:
            name = "%s_%d_%d" % (name, bitvec_counter.next(), size)
        return self._do_op('BitVec', (name, size), variables={ name }, raw=True, symbolic=True, simplified=True)
    BV = BitVec

    def BitVecVal(self, *args):
        return E(self, BVV(*args), set(), False, simplified=True)
        #return self._do_op('BitVecVal', args, variables=set(), symbolic=False, raw=True)
    BVV = BitVecVal

    # Bitwise ops
    def LShR(self, *args): return self._do_op('LShR', args)
    def SignExt(self, *args): return self._do_op('SignExt', args)
    def ZeroExt(self, *args): return self._do_op('ZeroExt', args)
    def Extract(self, *args): return self._do_op('Extract', args)
    def Concat(self, *args): return self._do_op('Concat', args)
    def RotateLeft(self, *args): return self._do_op('RotateLeft', args)
    def RotateRight(self, *args): return self._do_op('RotateRight', args)
    def Reverse(self, o, lazy=True):
        if type(o) is not E or not lazy:
            return self._do_op('Reverse', (o,))

        if isinstance(o.ast, A) and o.ast.op == 'Reverse':
            return self.wrap(o.ast.args[0])
        else:
            return self.wrap(A(self, "Reverse", (o,)), symbolic=o.symbolic, variables=o.variables)

    #
    # Strided interval
    #
    def StridedInterval(self, name=None, bits=0, lower_bound=None, upper_bound=None, stride=None, to_conv=None):
        si = BackendVSA.CreateStridedInterval(name=name,
                                            bits=bits,
                                            lower_bound=lower_bound,
                                            upper_bound=upper_bound,
                                            stride=stride,
                                            to_conv=to_conv)
        return E(self, si, variables={ si.name }, symbolic=False)
    SI = StridedInterval

    def TopStridedInterval(self, bits, signed=False):
        si = BackendVSA.CreateTopStridedInterval(bits=bits, signed=signed)
        return E(self, si, variables={ si.name }, symbolic=False)
    TSI = TopStridedInterval

    # Value Set
    def ValueSet(self, **kwargs):
        vs = ValueSet(**kwargs)
        return E(self, vs, set(), symbolic=False)
    VS = ValueSet

    # a-loc
    def AbstractLocation(self, *args, **kwargs): #pylint:disable=no-self-use
        aloc = AbstractLocation(*args, **kwargs)
        return aloc

    #
    # Boolean ops
    #
    def BoolVal(self, *args):
        return E(self, args[0], set(), False, simplified=True)
        #return self._do_op('BoolVal', args, variables=set(), symbolic=False, raw=True)

    def And(self, *args): return self._do_op('And', args)
    def Not(self, *args): return self._do_op('Not', args)
    def Or(self, *args): return self._do_op('Or', args)
    def ULT(self, *args): return self._do_op('ULT', args)
    def ULE(self, *args): return self._do_op('ULE', args)
    def UGE(self, *args): return self._do_op('UGE', args)
    def UGT(self, *args): return self._do_op('UGT', args)

    #
    # Other ops
    #
    def If(self, *args):
        if len(args) != 3: raise ClaripyOperationError("invalid number of args passed to If")
        return self._do_op('If', args)

    def Identical(self, *args):
        '''
        Attempts to check if the underlying models of the expression are identical,
        even if the hashes match.

        This process is somewhat conservative: False does not necessarily mean that
        it's not identical; just that it can't (easily) be determined to be identical.
        '''
        if not all([isinstance(a, E) for a in args]):
            return False

        if len(set(hash(a) for a in args)) == 1:
            return True

        first = args[0]
        identical = True
        for o in args:
            i = self._do_op_raw('Identical', (first, o))
            identical &= i is True
        return identical

    #def size(self, *args): return self._do_op('size', args)

    def ite_dict(self, i, d, default):
        return self.ite_cases([ (i == c, v) for c,v in d.items() ], default)

    def ite_cases(self, cases, default):
        sofar = default
        for c,v in reversed(cases):
            sofar = self.If(c, v, sofar)
        return sofar

    def simplify(self, e):
        for b in self.model_backends:
            try: return b.simplify_expr(e)
            except BackendError: pass

        l.debug("Simplifying via solver backend")

        for b in self.solver_backends:
            try: return b.simplify_expr(e)
            except BackendError: pass

        l.warning("Unable to simplify expression")
        return e

    def is_true(self, e):
        for b in self.model_backends:
            try: return b.is_true(b.convert_expr(e))
            except BackendError: pass

        l.warning("Unable to tell the truth-value of this expression")
        return False

    def is_false(self, e):
        for b in self.model_backends:
            try:
                return b.is_false(b.convert_expr(e))
            except BackendError:
                pass

        l.warning("Unable to tell the truth-value of this expression")
        return False

    def constraint_to_si(self, expr, bits):
        '''
        Convert a constraint to SI if possible
        :param expr:
        :return:
        '''
        si = None

        for b in self.model_backends:
            if b is BackendVSA:
                si = b.constraint_to_si(expr)

        if si is None:
            return self.TopStridedInterval(bits)
        else:
            return si

    def model_object(self, e, result=None):
        for b in self.model_backends:
            try: return b.convert_expr(e, result=result)
            except BackendError: pass
        raise BackendError('no model backend can convert expression')

from .expression import E
from .ast import A
from .backends.backend import BackendError
from .bv import BVV
from .vsa import ValueSet, AbstractLocation
from .backends import BackendVSA
from .errors import ClaripyOperationError
