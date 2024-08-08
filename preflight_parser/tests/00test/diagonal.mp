%
% diagonal.mp
%

%prologues:=1;

defaultfont:="ecrm1000";
u = 1cm;


def exline(expr p,q) =
  begingroup;
    pair d;
    d = (q-p) scaled (0.3u/length(q-p));
    draw (p-d)--(q+d);
  endgroup;
enddef;

def exxline(expr p,q,l,m) =
  begingroup;
    pair d[];
    d0 = (q-p) scaled (l/length(q-p));
    d1 = (q-p) scaled (m/length(q-p));
    draw (p-d0)--(q+d1);
  endgroup;
enddef;

def exbow(expr p,q,r) =
  begingroup;
    pair tp[],dire[];
    path pa;
    pa = p..q..r;
    dire0 = direction 0 of pa;
    dire1 = direction 2 of pa;
    tp0 = p - (dire0 scaled (0.2u/length(dire0)));
    tp1 = r + (dire1 scaled (0.2u/length(dire1)));
    draw tp0..p..q..r..tp1;
  endgroup;
enddef;

def circle(expr p) =
  draw fullcircle scaled circlerad shifted p;
enddef;

sbarlen = dbarlen = sqrt2;
circlerad = 0.2u;

verbatimtex \def\cI{\mathrel{\cal I}}\def\cnotI{\mathrel{\cI\!\!\!\!|\,}} etex

beginfig(1);
  uu = 0.2cm;
  z.b = (0,0); z.l = (15uu,0); z.e = (27uu,0); z.c = (30uu,0);
  z.f = (0,18uu); z.a = (3uu,18uu); z.m = (15uu,18uu); z.d = (27uu,18uu);
  draw z.b--z.f--z.d--z.c--z.b--z.a;
  draw z.d--z.e; draw z.m--z.l;
  dotlabel.bot(btex $B$ etex, z.b);
  dotlabel.bot(btex $L$ etex, z.l);
  dotlabel.bot(btex $E$ etex, z.e);
  dotlabel.bot(btex $C$ etex, z.c);
  dotlabel.top(btex $F$ etex, z.f);
  dotlabel.top(btex $A$ etex, z.a);
  dotlabel.top(btex $M$ etex, z.m);
  dotlabel.top(btex $D$ etex, z.d);
  label.top("15", 0.5[z.b,z.l]);
  label.top("12",0.5[z.l,z.e]);
  label.bot("12",0.5[z.a,z.m]);
  label.bot("12",0.5[z.m,z.d]);
  draw (15uu,-3uu)--(15uu,-5uu); draw (30uu,-3uu)--(30uu,-5uu);
  draw (15uu,-4uu)--(21uu,-4uu); draw (24uu,-4uu)--(30uu,-4uu);
  label("15",(22.5uu,-4uu));
  draw (0,39uu)--(0,41uu); draw (27uu,39uu)--(27uu,41uu);
  draw (0,40uu)--(12uu,40uu); draw (15uu,40uu)--(27uu,40uu);
  label("27",(13.5uu,40uu));
endfig;

beginfig(2);
  z0=(0,0); z1=(6u,0);
  drawarrow z0--z1;
  drawarrow (z0--z1) shifted (0,0.8u);
  drawarrow (z0--z1) shifted (0,1.6u);
endfig;

beginfig(3);
  z0 = (4u,0);
  z.s = (0,0);
  z.t = (2u,0);
  z.r = (0,2u);
  z.x = (2u,2u);
  z.q = (u,u);
  z.rk = z.r + z0;
  z.xp = z.x + z0;
  z.tk = z.t + z0;
  z.sk = z.q + z0;
  exline(z.s,z.x); exline(z.r,z.t); exline(z.rk,z.tk); exline(z.xp,z.sk);
  dotlabel.llft(btex $R$ etex, z.r);
  dotlabel.lrt(btex $X$ etex,z.x);
  dotlabel.ulft(btex $S$ etex, z.s);
  dotlabel.urt(btex $T$ etex, z.t);
  dotlabel.rt(btex $Q$ etex, z.q);
  dotlabel.llft(btex $R\kappa$ etex, z.rk);
  dotlabel.urt(btex $T\kappa$ etex, z.tk);
  dotlabel.lrt(btex $X'$ etex, z.xp);
  dotlabel.rt(btex $S\kappa$ etex, z.sk);
endfig;

beginfig(4);
  z0=(0,0); z1=(6u,0); z2=(3u,u); z3=(3u,-u);
  exbow(z0,z2,z1);
  exbow(z0,z3,z1);
  dotlabel.bot(btex $P$ etex, z0);
  dotlabel.bot(btex $Q$ etex, z1);
  dotlabel.top(btex $g$ etex, z2);
  dotlabel.bot(btex $h$ etex, z3);
endfig;

beginfig(5);
  draw (0,0)--(4.5u,0); draw (4u,-0.5u)--(4u,3u);
  dotlabel.top(btex $Q$ etex,(1u,0u));
  dotlabel.top(btex $R$ etex,(3u,0u));
  dotlabel.rt(btex $X$ etex,(4u,1u));
  dotlabel.top(btex $P$ etex, (2u,2u));
  label.rt(btex $g$ etex, (4u,2.8u));
endfig;

beginfig(6);
  draw (0,0)--(2.5u,2.5u); draw (4u,0)--(1.5u,2.5u);
  dotlabel.ulft(btex $t$ etex,(u,u));
  dotlabel.urt(btex $u$ etex,(3u,u));
  dotlabel.top(btex $Q$ etex,(2u,2u));
  label.ulft(btex $g$ etex,(0,0));
  label.urt(btex $h$ etex, (4u,0));
endfig;

beginfig(7);
  z.A=(0,0);
  z.B=(3u,0.5u);
  z.D=(0.5u,4u);
  z.C=(2.5u,2.5u);
  z.E=whatever[z.A,z.B]=whatever[z.C,z.D];
  z.F=whatever[z.A,z.C]=whatever[z.B,z.D];
  exxline(z.A,z.E,u,0.3u); exxline(z.A,z.C,0.3u,u);
  exxline(z.D,z.E,u,0.3u);
  exxline(z.B,z.D,1u,0.3u);
  exxline(z.F,z.E,2u,0.3u);
  dotlabel.bot(btex $A_0$ etex, z.A);
  dotlabel.bot(btex $B_0$ etex, z.B);
  dotlabel.bot(btex $C_0$ etex, z.C);
  dotlabel.bot(btex $D_0$ etex, z.D);
  dotlabel.bot(btex $E$ etex, z.E);
  dotlabel.bot(btex $F$ etex, z.F);
  z.g=(-0.2)[z.A,z.B];
  label.top(btex $g$ etex,z.g);
  z.h=(-0.3)[z.D,z.C];
  label.bot(btex $h$ etex,z.h);
  z.j=(1.1)[z.A,z.C];
  label.rt(btex $j$ etex,z.j);
  z.k=(-0.19)[z.B,z.D];
  label.lft(btex $k$ etex,z.k);
  z.l=(-0.4)[z.F,z.E];
  label.top(btex $l$ etex,z.l);
endfig;
    
beginfig(8);
  z1=(10u,10u);
  circle(z1); z2=z1+(0,-dbarlen*u); draw z1--z2;
  circle(z2); z3l=z2+(-u,-u); z3r=z2+(u,-u); draw z3l--z2--z3r;
  circle(z3r); circle(z3l);
  z4l=z3r+(-u,-u); z4r=z3r+(u,-u); draw z4l--z3r--z4r;
  circle(z4r); circle(z4l);
  z5l=z4r+(-u,-u); z5r=z4r+(u,-u); draw z5l--z4r--z5r;
  circle(z5l); circle(z5r);
  z1m=.5[z1,z2];
  z2lm=.5[z2,z3l]; z2rm=.5[z2,z3r];
  z3lm=.5[z3r,z4l]; z3rm=.5[z3r,z4r];
  z4lm=.5[z4r,z5l]; z4rm=.5[z4r,z5r];
  z.s=(0,-0.2u);
  label.rt(btex Construction of the terms etex,z1m);
  label.lft(btex $A\cnotI l$ etex,z2lm); label.rt(btex $A\cI l$ etex,z2rm);
  label.lft(btex $A=E$ etex,z3lm); label.rt(btex $g=l$ etex,z3rm);
  label.lft(btex $A=F$ etex,z4lm); label.rt(btex $g=j$ etex,z4rm);
  label.llft(btex $\displaystyle A\cI h\atop \displaystyle A\cnotI h$ etex,z4l+z.s);
  label.llft(btex $\displaystyle C\cI g\atop \displaystyle C\cnotI g$ etex,z5l+z.s);
  label.lrt(btex $\displaystyle A\cI k\atop \displaystyle A\cnotI k$ etex,z5r+z.s);
  label.llft(btex $A\cnotI l$ etex,z3l+z.s);
  label.rt(btex \hbox{\hskip3pt 1} etex, z1);
  label.rt(btex \hbox{\hskip3pt 2} etex, z2);
  label.lft(btex \hbox{3l\hskip3pt} etex, z3l);
  label.lft(btex \hbox{4l\hskip3pt} etex, z4l);
  label.lft(btex \hbox{5l\hskip3pt} etex, z5l);
  label.rt(btex \hbox{\hskip3pt 3r} etex, z3r);
  label.rt(btex \hbox{\hskip3pt 4r} etex, z4r);
  label.rt(btex \hbox{\hskip3pt 5r} etex, z5r);
endfig;

beginfig(9);
  z.p  = (-2u,u);       z.q  = (1.3u,1.733u);    z.r  = (0.125u,2.932u);
  z.pp = (-2.6u,-0.5u); z.qq = (2.167u,-1.111u); z.rr = (0.368u,-3.486u);
  z.o = whatever[z.p,z.pp] = whatever[z.q,z.qq];
  z.a = whatever[z.p,z.q] = whatever[z.pp,z.qq];
  z.b = whatever[z.p,z.r] = whatever[z.pp,z.rr];
  z.c = whatever[z.q,z.r] = whatever[z.qq,z.rr];
  draw z.o--z.pp; draw z.o--z.rr; draw z.o--z.qq;
  draw z.a--z.q; draw z.a--z.qq;
  draw z.b--z.r; draw z.b--z.rr;
  draw z.c--z.r; draw z.c--z.rr;
  exline(z.a,z.c);
  dotlabel.llft(btex $P'$ etex, z.pp); 
  dotlabel.lrt(btex $R'$ etex, z.rr); 
  dotlabel.lrt(btex $Q'$ etex, z.qq); 
  dotlabel.ulft(btex $P$ etex, z.p); 
  dotlabel.urt(btex $R$ etex, z.r); 
  dotlabel.urt(btex $Q$ etex, z.q);
  dotlabel.top(btex $O$ etex, z.o);
  dotlabel("",z.a); dotlabel("",z.b); dotlabel("",z.c);
  label.top(btex $o$ etex,z.c+((z.c-z.a) scaled (0.2u/length(z.c-z.a))));
endfig;


beginfig(10);
  z.a = (0,0);
  z.b = (8u,0);
  z.c = (4u,4*(sqrt3)*u);
  z.d1 = .5[z.a,z.b];
  z.d2 = .5[z.a,z.c];
  z.d3 = .5[z.b,z.c];
  z.d0 = z.a+whatever*(z.d3-z.a) = z.b+whatever*(z.d2-z.b);
  draw z.a--z.b--z.c--cycle;
  draw z.d1--z.c; draw z.d2--z.b; draw z.d3--z.a;
  dotlabel.top(btex $C_0$ etex,z.c);
  dotlabel.llft(btex $A_0$ etex,z.a);
  dotlabel.lrt(btex $B_0$ etex,z.b);
  dotlabel.bot(btex $D_0$ etex, z.d0);
  dotlabel.bot(btex $D_1$ etex, z.d1);
  dotlabel.urt(btex $D_3$ etex, z.d3);
  dotlabel.ulft(btex $D_2$ etex, z.d2);
  draw z.d1..z.d2..z.d3..cycle;
endfig;


beginfig(11);
  picture p;
  p = btex $A(\vec t_1, \vec T_1) \lor \ldots \lor A(\vec t_n, \vec T_n)$ etex;
  z.ur = urcorner p;
  z.ul = ulcorner p;
  z.ll = llcorner p;
  z.lr = lrcorner p;
  z.b1l = 0.05[z.ul,z.ur];
  z.b1r = 0.6[z.ul,z.ur];
  z.b2l = 0.3[z.ul,z.ur];
  z.b2r = 0.95[z.ul,z.ur];
  z.b3l = 0.2[z.ll,z.lr];
  z.b3r = 0.4[z.ll,z.lr];
  z.b4l = 0.5[z.ll,z.lr];
  z.b4r = 0.6[z.ll,z.lr];
  draw p;
  draw z.b1l{dir 30}..{dir -30}z.b1r;
  draw z.b2l{dir 30}..{dir -30}z.b2r;
  draw z.b3l{dir -45}..{dir 45}z.b3r;
  draw z.b4l{dir -45}..{dir 45}z.b4r;
endfig;

    
beginfig(12);
  z1=(10u,10u);
  circle(z1);
  z2l=z1+(-u,-u); z2r=z1+(u,-u); draw z2l--z1--z2r;
  circle(z2r); circle(z2l);
  z3=z2r+(0,-dbarlen*u); draw z2r--z3; circle(z3);
  z4=z3+(0,-dbarlen*u); draw z3--z4; circle(z4);
  z5l=z4+(-u,-u); z5r=z4+(u,-u); draw z5l--z4--z5r;
  circle(z5r); circle(z5l);
  z6=z5r+(0,-dbarlen*u); draw z5r--z6; circle(z6);
  z7=z6+(0,-dbarlen*u); draw z6--z7; circle(z7);
  z1m=.5[z1,z2r]; z4m=.5[z4,z5r];
  label.rt(btex \hbox{\hskip3pt 1} etex, z1);
  label.lft(btex \hbox{2l\hskip3pt} etex, z2l);
  label.rt(btex \hbox{\hskip3pt 2r} etex, z2r);
  label.rt(btex \hbox{\hskip3pt 3} etex, z3);
  label.rt(btex \hbox{\hskip3pt 4} etex, z4);
  label.lft(btex \hbox{5l\hskip3pt} etex, z5l);
  label.rt(btex \hbox{\hskip3pt 5r} etex, z5r);
  label.rt(btex \hbox{\hskip3pt 6} etex, z6);
  label.rt(btex \hbox{\hskip3pt 7} etex, z7);
  label.rt(btex critical constellation etex, z1m);
  label.rt(btex critical constellation etex, z4m);
endfig;

end.








