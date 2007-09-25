# Hedge - the Hybrid'n'Easy DG Environment
# Copyright (C) 2007 Andreas Kloeckner
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.




import pylinear.array as num
import pylinear.computation as comp
from pytools.arithmetic_container import \
        ArithmeticList, \
        work_with_arithmetic_containers, \
        join_fields
from hedge.tools import Rotation, dot




def coefficient_to_matrix(discr, coeff):
    return num.diagonal_matrix(
            discr.interpolate_volume_function(coeff),
            flavor=num.SparseExecuteMatrix)

    



class StrongHeatOperator:
    def __init__(self, discr, coeff=lambda x: 1, 
            dirichlet_bc=lambda x, t: 0, dirichlet_tag="dirichlet",
            neumann_bc=lambda x, t: 0, neumann_tag="neumann"):
        self.discr = discr

        from hedge.flux import \
                FluxVectorPlaceholder, \
                FluxScalarPlaceholder, \
                make_normal

        dim = discr.dimensions
        u = FluxScalarPlaceholder(0)
        v = FluxVectorPlaceholder(dim)
        normal = make_normal(dim)

        flux_central_v = dot(v.int, normal) - dot(v.avg, normal)
        flux_central_u = u.int*normal - u.avg*normal

        ldg_beta = ArithmeticList([1]*dim)
        flux_ldg_v = flux_central_v + dot((v.int-v.ext)*0.5, ldg_beta)
        flux_ldg_u = flux_central_u -(u.int-u.ext)*0.5*ldg_beta

        self.flux_u = discr.get_flux_operator(flux_ldg_u)
        self.flux_v = discr.get_flux_operator(flux_ldg_v)
        self.flux_u_bdry = discr.get_flux_operator(flux_central_u)
        self.flux_v_bdry = discr.get_flux_operator(flux_central_v)

        self.nabla = discr.nabla
        self.stiff = discr.stiffness_operator
        self.mass = discr.mass_operator
        self.m_inv = discr.inverse_mass_operator

        from math import sqrt
        self.coeff_func = coeff
        self.sqrt_coeff = coefficient_to_matrix(discr, lambda x: sqrt(coeff(x)))
        self.dirichlet_bc_func = dirichlet_bc
        self.dirichlet_tag = dirichlet_tag
        self.neumann_bc_func = neumann_bc
        self.neumann_tag = neumann_tag

        self.neumann_normals = discr.boundary_normals(self.neumann_tag)

    def v(self, t, u):
        from hedge.discretization import pair_with_boundary
        from math import sqrt

        def dir_bc_func(x):
            return sqrt(self.coeff_func(x))*self.dirichlet_bc_func(t, x)

        dtag = self.dirichlet_tag
        ntag = self.neumann_tag

        sqrt_coeff_u = self.sqrt_coeff * u

        dirichlet_bc_u = (
                -self.discr.boundarize_volume_field(sqrt_coeff_u, dtag)
                +2*self.discr.interpolate_boundary_function(dir_bc_func, dtag))

        neumann_bc_u = self.discr.boundarize_volume_field(sqrt_coeff_u, ntag)

        self.flux_u*sqrt_coeff_u
        self.flux_u_bdry*pair_with_boundary(sqrt_coeff_u, dirichlet_bc_u, dtag)
        self.flux_u_bdry*pair_with_boundary(sqrt_coeff_u, neumann_bc_u, ntag)

        return self.m_inv * (
                self.sqrt_coeff*(self.stiff * u)
                - self.flux_u*sqrt_coeff_u
                - self.flux_u_bdry*pair_with_boundary(sqrt_coeff_u, dirichlet_bc_u, dtag)
                - self.flux_u_bdry*pair_with_boundary(sqrt_coeff_u, neumann_bc_u, ntag)
                )

    def rhs(self, t, u):
        from hedge.discretization import pair_with_boundary
        from math import sqrt

        def neumann_bc_func(x):
            return sqrt(self.coeff_func(x))*self.neumann_bc_func(t, x)

        v = self.v(t, u)

        dtag = self.dirichlet_tag
        ntag = self.neumann_tag

        ac_multiply = work_with_arithmetic_containers(num.multiply)

        sqrt_coeff_v = self.sqrt_coeff * v
        dirichlet_bc_v = self.discr.boundarize_volume_field(sqrt_coeff_v, dtag)
        neumann_bc_v = (
                -self.discr.boundarize_volume_field(sqrt_coeff_v, ntag)
                +
                2*ac_multiply(self.neumann_normals,
                self.discr.interpolate_boundary_function(neumann_bc_func, ntag))
                )

        return self.m_inv * (
                dot(self.stiff, self.sqrt_coeff*v)
                - self.flux_v * sqrt_coeff_v
                - self.flux_v_bdry * pair_with_boundary(sqrt_coeff_v, dirichlet_bc_v, dtag)
                - self.flux_v_bdry * pair_with_boundary(sqrt_coeff_v, neumann_bc_v, ntag)
                )




def main() :
    from hedge.element import \
            TriangularElement, \
            TetrahedralElement
    from hedge.timestep import RK4TimeStepper
    from hedge.mesh import \
            make_disk_mesh, \
            make_regular_square_mesh, \
            make_square_mesh, \
            make_ball_mesh
    from hedge.visualization import SiloVisualizer, VtkVisualizer
    from math import sin, cos, pi, exp, sqrt
    from hedge.parallel import guess_parallelization_context

    pcon = guess_parallelization_context()

    dim = 2

    def boundary_tagger(fvi, el, fn):
        if el.face_normals[fn][0] > 0:
            return ["dirichlet"]
        else:
            return ["neumann"]

    if dim == 2:
        if pcon.is_head_rank:
            mesh = make_disk_mesh(r=0.5, boundary_tagger=boundary_tagger)
            #mesh = make_regular_square_mesh(
                    #n=9, periodicity=(True,True))
            #mesh = make_regular_square_mesh(n=9)
            #mesh = make_square_mesh(max_area=0.008)
            #mesh.transform(Rotation(pi/8))
        el_class = TriangularElement
    elif dim == 3:
        if pcon.is_head_rank:
            mesh = make_ball_mesh(max_volume=0.001)
        el_class = TetrahedralElement
    else:
        raise RuntimeError, "bad number of dimensions"

    if pcon.is_head_rank:
        print "%d elements" % len(mesh.elements)
        mesh_data = pcon.distribute_mesh(mesh)
    else:
        mesh_data = pcon.receive_mesh()

    discr = pcon.make_discretization(mesh_data, el_class(3))
    stepper = RK4TimeStepper()
    vis = VtkVisualizer(discr, "fld", pcon)

    dt = discr.dt_factor(1)**2/5
    nsteps = int(1/dt)
    if pcon.is_head_rank:
        print "dt", dt
        print "nsteps", nsteps

    def u0(x):
        if comp.norm_2(x) < 0.2:
            #return exp(-100*x*x)
            return 1
        else:
            return 0

    def coeff(x):
        if x[0] < 0:
            return 0.25
        else:
            return 1

    def dirichlet_bc(t, x):
        return 0

    def neumann_bc(t, x):
        return 2

    op = StrongHeatOperator(discr, 
            #coeff=coeff,
            dirichlet_tag=None,
            dirichlet_bc=dirichlet_bc,
            neumann_tag="garnix", 
            #neumann_bc=neumann_bc
            )
    u = discr.interpolate_volume_function(u0)

    for step in range(nsteps):
        t = step*dt
        if step % 10 == 0:
            print "timestep %d, t=%f, l2=%g" % (
                    step, t, sqrt(u*(op.mass*u)))

        if step % 10 == 0:
            visf = vis.make_file("fld-%04d" % step)
            vis.add_data(visf,
                    [("u", u), ], 
                    time=t, step=step, 
                    #write_coarse_mesh=True
                    )
            visf.close()

        u = stepper(u, t, dt, op.rhs)

if __name__ == "__main__":
    #import cProfile as profile
    #profile.run("main()", "wave2d.prof")
    main()
