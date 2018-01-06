# -*-coding:utf-8 -*-
from flask import render_template, redirect, url_for, flash, request, jsonify, g
from werkzeug.utils import secure_filename
from form import LoginForm, RegisterForm, PostForm
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime
from model import User, Catalog, Article, Comment, Tag, articles_tags
from sqlalchemy import func
from . import db
from . import ALLOWED_EXTENSIONS
import json, os, datetime, decimal


def init_views(app):
    class DataEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, datetime.datetime):
                return datetime.strftime(obj, '%Y-%m-%d %H:%M').replace(' 00:00', '')
            elif isinstance(obj, datetime.date):
                return datetime.strftime(obj, '%Y-%m-%d')
            elif isinstance(obj, decimal.Decimal):
                return str(obj)
            elif isinstance(obj, float):
                return round(obj, 8)
            return json.JSONEncoder.default(self, obj)

    # @app.template_filter('eip_format')
    def eip_format(data):
        return json.dumps(data, json.dumps, cls=DataEncoder, ensure_ascii=False, indent=2)

    # 模板时间格式化
    @app.template_filter('dateformat')
    def dateformat(value, ft="%Y-%m-%d"):
        return value.strftime(ft)

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('404.html', title='Page Not Found'), 404

    @app.before_request
    def before_request():
        # 默认分页数
        g.pagesize = 8
        # 最新评论文章
        g.hot_list = db.session.execute('''
            SELECT COUNT(c.id) counts,a.id,a.title,a.visited,a.create_date,a.photo
            FROM comment c
            LEFT JOIN article a ON c.article_id = a.id
            GROUP BY a.id
            ORDER BY c.create_date DESC ''')

        g.user = current_user
        g.para = {'iflogin': request.args.get('login_required') or 'default'}
        # g.islogin = login()

    @app.teardown_request
    def teardown_request(exception):
        db.session.close()

    # 标签云
    def tags_cloud(catalog, keyword):
        tag_list = db.session.execute(u'''
                    SELECT COUNT(t.tag) AS num,t.tag FROM articles_tags at
                    LEFT JOIN article a ON a.id = at.article_id
                    LEFT JOIN catalog ca ON ca.id = a.catalog_id
                    LEFT JOIN tag t ON t.id = at.tag_id
                    WHERE ca.catalog = :v_catalog or :v_catalog = '搜索结果'
                    AND (a.title like concat('%',:keyword,'%')  or :keyword = '')
                    GROUP BY t.tag''', {'v_catalog': catalog, 'keyword': keyword})
        return tag_list

    # 主页
    @app.route('/', methods=['GET', 'POST'])
    @app.route('/index', methods=['GET', 'POST'])
    def index():
        para = {'page': request.args.get('page', 1, type=int),
                'url': 'index',
                'title': u'最新发布'}
        sql_para = {'pagesize': g.pagesize,
                    'nowcolumn': g.pagesize * (para['page'] - 1)}
        articles = db.session.execute(u'''
                    SELECT a.id,a.title,CONCAT(SUBSTR(a.body, 1, 200),'...') description,a.visited,
                        a.create_date,a.photo,cl.catalog,count(ct.id) AS counts,v.tag
                    FROM article a
                    LEFT JOIN comment ct on ct.article_id = a.id
                    LEFT JOIN catalog cl on cl.id = a.catalog_id
                    LEFT JOIN  (SELECT ats.article_id id,tg.tag
                                FROM articles_tags ats
                                LEFT JOIN tag tg ON tg.id = ats.tag_id
                                GROUP BY ats.article_id) v on v.id = a.id
                    GROUP BY a.id,a.title,a.description,a.visited,a.create_date,cl.catalog,v.tag
                    ORDER BY a.id DESC 
                    LIMIT :pagesize OFFSET :nowcolumn''', sql_para)
        return render_template('index.html', articles=articles, para=para, hots=g.hot_list)

    # 分类/搜索列表
    @app.route('/<catalog>', methods=['GET', 'POST'])
    def catalog_list(catalog):
        addr = {'notes': u'IT笔记', 'info': u'资讯', 'search': u'搜索结果'}
        para = {'page': request.args.get('page', 1, type=int),
                'keyword': request.args.get('keyword') or '',
                'tag': request.args.get('tag') or '',
                'title': addr[catalog],
                'url': catalog}
        sql_para = {'v_catalog': addr[catalog],
                    'keyword': para['keyword'],
                    'tag': para['tag'],
                    'pagesize': g.pagesize,
                    'nowcolumn': g.pagesize * (para['page'] - 1)}
        articles = db.session.execute(u'''
            SELECT a.id,a.title,CONCAT(SUBSTR(a.body, 1, 200),'...') description,a.visited,
                a.create_date,a.photo,cl.catalog,count(ct.id) AS counts,v.tag
            FROM article a
            LEFT JOIN comment ct on ct.article_id = a.id
            LEFT JOIN catalog cl on cl.id = a.catalog_id
            LEFT JOIN  (SELECT ats.article_id id,tg.tag
                        FROM articles_tags ats
                        LEFT JOIN tag tg ON tg.id = ats.tag_id
                        where tg.tag = :tag or :tag = ''
                        GROUP BY ats.article_id) v on v.id = a.id
            WHERE (cl.catalog = :v_catalog or :v_catalog = '搜索结果')
            AND (a.title like concat('%',:keyword,'%')  or :keyword = '')
            AND (v.tag = :tag or :tag = '')
            GROUP BY a.id,a.title,a.description,a.visited,a.create_date,cl.catalog,v.tag
            ORDER BY a.id DESC 
            {}'''.format('LIMIT :pagesize OFFSET :nowcolumn' if not para['keyword'] else ''), sql_para)
        return render_template('list.html',
                               articles=articles,
                               para=para,
                               hots=g.hot_list,
                               tags=tags_cloud(addr[catalog], para['keyword']))

    # 文章详情
    @app.route('/detail/<int:id>', methods=['GET', 'POST'])
    def detail(id):
        article = Article.query.get_or_404(id)
        para = {'username': request.form.get('username'),
                'email': request.form.get('email'),
                'comment': request.form.get('comment'),
                'comment_submit': request.form.get('comment_submit')}
        # 提交评论
        if para['comment_submit'] and para['username'] and para['comment']:
            comment = Comment(body=para['comment'],
                              create_user=para['username'],
                              email=para['email'],
                              article_id=id)
            db.session.add(comment)
            article.visited = article.visited - 1
            db.session.commit()
            return redirect(url_for('detail', id=article.id))

        article.visited = article.visited + 1
        db.session.commit()

        # 获取标签
        tags = db.session.execute('''
            SELECT t.tag FROM articles_tags at
            LEFT JOIN article a ON a.id = at.article_id
            LEFT JOIN tag t ON t.id = at.tag_id
            WHERE at.article_id = :id''', {'id': id})
        # 获取评论
        comments = db.session.execute('''
            SELECT
                @rownum :=@rownum + 1 AS row_num,
                REPLACE (c.body, CHAR(10), '<br>') body_html,
                c.*
            FROM comment c,
                 (SELECT @rownum := 0) r
            where c.article_id = :id
            ORDER BY row_num DESC''', {'id': id})

        return render_template('detail.html', article=article, comments=comments, tags=tags, hots=g.hot_list)

    # 登陆
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        login_form = LoginForm()
        if login_form.lg_submit.data and login_form.validate_on_submit():
            user = User.query.filter_by(username=login_form.username.data).first()
            # 验证密码
            if user is not None and user.password_hash == login_form.password.data:
                login_user(user, login_form.remember.data)
                return redirect(url_for('index'))
            flash(u'用户名或者密码错误！', 'error')
        # 注册成功时显示flash
        if g.para['iflogin'] == '2':
            flash(u'注册成功！现在您可以登录了', 'success')
        return render_template('login.html',
                               login_form=login_form,
                               hots=g.hot_list,
                               target='login')

    # 注册
    # @app.route('/register', methods=['GET', 'POST'])
    def register():
        register_form = RegisterForm()
        if register_form.re_submit.data and register_form.validate_on_submit():
            user = User(username=register_form.username.data,
                        password_hash=register_form.password.data)
            db.session.add(user)
            db.session.commit()
            return redirect(url_for('login', login_required=2))
        return render_template('login.html',
                               register_form=register_form,
                               para=g.para,
                               hots=g.hot_list,
                               target='register')

    # 登出
    @app.route('/logout', methods=['GET', 'POST'])
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('index'))

    # 发表文章
    @app.route('/write', methods=['GET', 'POST'])
    @app.route('/write/<int:id>', methods=['GET', 'POST'])
    @login_required
    def write(id=0):
        post_form = PostForm()
        # 标签
        tag_ids = []
        tagids = db.session.query(articles_tags).filter_by(article_id=id).all()
        for tagid in tagids:
            tag_ids.append(tagid[1])
        # 新增时
        if id == 0:
            # current_user._get_current_object()获取当前用户，只用current_user报错
            post = Article(create_user=g.user._get_current_object())
            page = {'catalog_id': '', 'id': id, 'tag_ids': tag_ids}
        # 修改时
        else:
            post = Article.query.get_or_404(id)
            post_form.description.data = post.description
            post_form.body.data = post.body
            post_form.title.data = post.title
            post_form.photo.data = post.photo
            page = {'catalog_id': post.catalog_id, 'id': id, 'tag_ids': tag_ids}
        # 提交内容
        if post_form.po_submit.data and post_form.validate_on_submit():
            post.title = request.form.get('title')
            post.description = request.form.get('description')
            post.catalog_id = request.form.get('catalog_id')
            post.body = request.form.get('body')
            post.photo = request.form.get('title') + '-' + secure_filename(request.files['photo'].filename)
            upload_file(request.files['photo'], request.form.get('title'))

            # 必填内容为空不提交
            if post.title and post.description and post.catalog_id:
                db.session.add(post)
                db.session.commit()
                # 更新标签
                db.session.execute('delete from articles_tags where article_id=:id', {'id': id})
                id = db.session.execute('select max(id) from article').first()[0] if id == 0 else id
                for tag_id in request.values.getlist('tag_id'):
                    db.session.execute('''
                                    insert into articles_tags (article_id,tag_id) 
                                    value (:id,:tag_id)
                                ''', {'id': id, 'tag_id': tag_id})
                db.session.commit()
                return redirect(url_for('detail', id=post.id))
        title = u'添加新文章'
        if id > 0:
            title = u'编辑 - %s' % post.title
        # 如果没有修改也没有新增，回滚Post(author=g.user._get_current_object())
        db.session.rollback()
        return render_template('write.html',
                               title=title,
                               post_form=post_form,
                               post=post,
                               catalogs=Catalog.query,
                               tags=Tag.query,
                               login_form=LoginForm(),
                               hots=g.hot_list,
                               page=eip_format(page))

    # 上传文件
    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS

    def upload_file(file, title):
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], title + '-' + filename))
